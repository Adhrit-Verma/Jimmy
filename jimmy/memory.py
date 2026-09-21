"""Jimmy's memory: things you told it, and what was said in chat.

Deliberately a separate file from the ambient capture DB. Captures are a record
of the screen that a retention policy will one day prune; memory is what Jimmy
keeps. Same engine (SQLite + FTS5), no second kind of database.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

STOPWORDS = set("""
a about above after again all am an and any are as at be been before being
between both but by can could did do does doing done during each for from had
has have having he her here hers him his how i if in into is it its just me
more most my no nor not now of off on once only or other our out over own same
she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which
while who whom why will with would you your yours
earlier today yesterday tonight morning afternoon evening week last ago just
remember recall tell show find thing things something anything stuff saw see
seen said say says talk talked talking looking look reading read watching
watch doing working minute minutes hour hours day days jimmy please
monday tuesday wednesday thursday friday saturday sunday
""".split())


def fts_query(text: str, max_terms: int = 8) -> str | None:
    """Natural language -> a safe FTS5 OR-query of the meaningful words.

    Every term is double-quoted, so punctuation and FTS operators in the user's
    words ("C++", "NOT", a stray quote) can never be read as query syntax.
    Returns None when nothing meaningful is left.
    """
    seen, terms = set(), []
    for word in re.findall(r"[\w][\w'-]*", text.lower()):
        word = word.strip("'-")
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.add(word)
        terms.append('"' + word.replace('"', "") + '"')
        if len(terms) >= max_terms:
            break
    return " OR ".join(terms) if terms else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, ts INT NOT NULL, source TEXT NOT NULL, text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, content='memories', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY, ts INT NOT NULL, session TEXT NOT NULL,
    role TEXT NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_turns_session ON turns(session, id);
"""


class Memory:
    def __init__(self, path: str | Path = ":memory:"):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def _write(self, sql: str, args: tuple) -> int:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def remember(self, text: str, source: str = "user") -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        return self._write("INSERT INTO memories(ts, source, text) VALUES (?,?,?)",
                           (int(time.time() * 1000), source, text))

    def forget(self, memory_id: int) -> None:
        self._write("DELETE FROM memories WHERE id=?", (memory_id,))

    def recall(self, question: str, limit: int = 5) -> list[dict]:
        q = fts_query(question)
        if not q:
            return []
        sql = """SELECT m.id, m.ts, m.source, m.text FROM memories_fts
                   JOIN memories m ON m.id = memories_fts.rowid
                  WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (q, limit))]

    def add_turn(self, session: str, role: str, text: str) -> None:
        if text and text.strip():
            self._write("INSERT INTO turns(ts, session, role, text) VALUES (?,?,?,?)",
                        (int(time.time() * 1000), session, role, text.strip()))

    def recent_turns(self, session: str, n: int) -> list[dict]:
        sql = """SELECT role, text FROM (SELECT id, role, text FROM turns WHERE session=?
                  ORDER BY id DESC LIMIT ?) ORDER BY id"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (session, n))]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
