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
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, created INT NOT NULL, text TEXT NOT NULL,
    due_ts INT, app TEXT, state TEXT DEFAULT 'waiting'
);
-- D41: editing a remembered fact keeps the search index in step.
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text);
END;
-- D41: what you're working towards, in your words. "Focus on X" also makes X a goal.
-- D42: what Jimmy heard, how, what it decided and did, and what it said. One row a request.
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY, ts INT NOT NULL, heard TEXT, via TEXT, route TEXT,
    steps TEXT, said TEXT, ms INT
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY, created INT NOT NULL, text TEXT NOT NULL,
    state TEXT DEFAULT 'active', done_ts INT
);
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

    # --- D41: reading and editing what Jimmy keeps, by voice or in the Memory tab ---
    def memories(self, limit: int = 100) -> list[dict]:
        """Facts you asked Jimmy to remember, newest first (focus history excluded)."""
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT id, ts, text FROM memories WHERE source != 'intent' ORDER BY id DESC LIMIT ?", (limit,))]

    def update_memory(self, memory_id: int, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            n = self.conn.execute("UPDATE memories SET text=? WHERE id=? AND source != 'intent'",
                                  (text, memory_id)).rowcount
            self.conn.commit()
        return bool(n)

    def add_goal(self, text: str) -> int | None:
        """A goal, unless the same one is already active (then its id)."""
        text = " ".join((text or "").split())
        if not text:
            return None
        with self._lock:
            row = self.conn.execute("SELECT id FROM goals WHERE state='active' AND lower(text)=lower(?)",
                                    (text,)).fetchone()
        return row[0] if row else self._write("INSERT INTO goals(created, text) VALUES (?,?)",
                                              (int(time.time() * 1000), text))

    def goals(self, state: str | None = "active") -> list[dict]:
        with self._lock:
            sql = "SELECT id, created, text, state, done_ts FROM goals"
            rows = (self.conn.execute(sql + " WHERE state=? ORDER BY id", (state,)) if state
                    else self.conn.execute(sql + " WHERE state != 'deleted' ORDER BY state, id"))
            return [dict(r) for r in rows]

    def update_goal(self, goal_id: int, text: str | None = None, state: str | None = None) -> bool:
        sets, args = [], []
        if text and text.strip():
            sets.append("text=?")
            args.append(" ".join(text.split()))
        if state in ("active", "done", "deleted"):
            sets += ["state=?", "done_ts=?"]
            args += [state, int(time.time() * 1000) if state == "done" else None]
        if not sets:
            return False
        with self._lock:
            n = self.conn.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id=?", (*args, goal_id)).rowcount
            self.conn.commit()
        return bool(n)

    def recall(self, question: str, limit: int = 5) -> list[dict]:
        q = fts_query(question)
        if not q:
            return []
        sql = """SELECT m.id, m.ts, m.source, m.text FROM memories_fts
                   JOIN memories m ON m.id = memories_fts.rowid
                  WHERE memories_fts MATCH ? ORDER BY bm25(memories_fts) LIMIT ?"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (q, limit))]

    # FOCUS needs a model of intent, not of the current window (AMBIENT_LAYER.md).
    # Intent is only what the user states; Jimmy never guesses it.
    _NO_INTENT = "(no current focus)"

    def set_intent(self, text: str | None) -> None:
        """State what you mean to be doing, or clear it with None/empty. D41: a stated
        focus is also a goal, so it shows (and can be finished) in the goals list."""
        self._write("INSERT INTO memories(ts, source, text) VALUES (?,?,?)",
                    (int(time.time() * 1000), "intent",
                     (text or "").strip() or self._NO_INTENT))
        if text and text.strip():
            self.add_goal(text)

    def current_intent(self, max_age_h: float, now_ms: int | None = None) -> dict | None:
        now_ms = now_ms or int(time.time() * 1000)
        with self._lock:
            row = self.conn.execute(
                "SELECT ts, text FROM memories WHERE source='intent' AND ts <= ? "
                "ORDER BY id DESC LIMIT 1", (now_ms,)).fetchone()
        if not row or row["text"] == self._NO_INTENT or now_ms - row["ts"] > max_age_h * 3600_000:
            return None
        return dict(row)

    # Reminders (D32): only ever what the user asked for, in their words. Due at a
    # time, or when an app comes to the front ("when I open Chrome"). Never deleted:
    # done or cancelled is a state.
    def add_reminder(self, text: str, due_ts: int | None = None, app: str | None = None) -> int:
        return self._write("INSERT INTO reminders(created, text, due_ts, app) VALUES (?,?,?,?)",
                           (int(time.time() * 1000), text.strip(), due_ts, (app or "").lower() or None))

    def due_reminders(self, now_ms: int, app: str | None = None) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT id, text, due_ts, app FROM reminders WHERE state = 'waiting' AND "
                "((due_ts IS NOT NULL AND due_ts <= ?) OR (app IS NOT NULL AND ? LIKE '%' || app || '%'))",
                (now_ms, (app or "").lower() or "\x00"))]

    def reminders(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT id, text, due_ts, app FROM reminders WHERE state = 'waiting' ORDER BY COALESCE(due_ts, 1e18)")]

    def update_reminder(self, rid: int, text: str | None = None, due_ts: int | None = None) -> bool:
        """D41: "move that reminder to 10 tomorrow", "change it to call Sam"."""
        sets, args = [], []
        if text and text.strip():
            sets.append("text=?")
            args.append(text.strip())
        if due_ts:
            sets.append("due_ts=?")
            args.append(due_ts)
        if not sets:
            return False
        with self._lock:
            n = self.conn.execute(f"UPDATE reminders SET {', '.join(sets)} WHERE id=? AND state='waiting'",
                                  (*args, rid)).rowcount
            self.conn.commit()
        return bool(n)

    def set_reminder_state(self, rid: int | None, state: str) -> None:
        """One reminder, or every waiting one when `rid` is None."""
        if rid is None:
            self._write("UPDATE reminders SET state = ? WHERE state = 'waiting'", (state,))
        else:
            self._write("UPDATE reminders SET state = ? WHERE id = ?", (state, rid))

    # Settings the user changed by voice ("speak softer"), kept across runs (D35).
    def setting(self, key: str, default=None):
        with self._lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value) -> None:
        self._write("INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def add_turn(self, session: str, role: str, text: str) -> None:
        if text and text.strip():
            self._write("INSERT INTO turns(ts, session, role, text) VALUES (?,?,?,?)",
                        (int(time.time() * 1000), session, role, text.strip()))

    def forget_turns(self, since_ms: int, until_ms: int) -> int:
        """D39: chat turns in a span the user deleted (answers quote what was captured).
        Remembered facts and reminders stay: those you asked Jimmy to keep."""
        with self._lock:
            n = self.conn.execute("DELETE FROM turns WHERE ts >= ? AND ts < ?", (since_ms, until_ms)).rowcount
            self.conn.commit()
        return n

    def add_trace(self, t: dict) -> None:
        import json
        self._write("INSERT INTO traces(ts, heard, via, route, steps, said, ms) VALUES (?,?,?,?,?,?,?)",
                    (int(t.get("ts") or time.time() * 1000), str(t.get("heard") or "")[:500], t.get("via") or "",
                     t.get("route") or "", json.dumps(t.get("steps") or [], ensure_ascii=False)[:8000],
                     str(t.get("said") or "")[:500], int(t.get("ms") or 0)))

    def traces(self, n: int = 20) -> list[dict]:
        import json
        with self._lock:
            rows = [dict(r) for r in self.conn.execute("SELECT * FROM traces ORDER BY id DESC LIMIT ?", (n,))]
        for r in rows:
            r["steps"] = json.loads(r["steps"] or "[]")
        return rows

    def recent_turns(self, session: str, n: int) -> list[dict]:
        sql = """SELECT role, text FROM (SELECT id, role, text FROM turns WHERE session=?
                  ORDER BY id DESC LIMIT ?) ORDER BY id"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (session, n))]

    def close(self) -> None:
        with self._lock:
            self.conn.close()
