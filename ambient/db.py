"""SQLite + FTS5 store for the context bus.

Schema follows AMBIENT_LAYER.md. Note what is absent: no `faces` table and no
`people` table. That is deliberate and must stay that way -- see Stage 1b.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

# `evidence` is declared TEXT rather than the spec's JSON: SQLite gives an
# unrecognised type name NUMERIC affinity, which would coerce numeric-looking
# payloads. Content is still JSON.
SCHEMA = """
CREATE TABLE IF NOT EXISTS capture_windows (
    id TEXT PRIMARY KEY, opened_at INT NOT NULL, closed_at INT, kind TEXT
);
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY, ts INT NOT NULL,
    window_id TEXT REFERENCES capture_windows(id),
    app TEXT, title TEXT, thumb_path TEXT, face_count INT DEFAULT 0
);
CREATE TABLE IF NOT EXISTS text_blocks (
    id INTEGER PRIMARY KEY,
    frame_id INT REFERENCES frames(id) ON DELETE CASCADE,
    source TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audio_segments (
    id INTEGER PRIMARY KEY, ts_start INT NOT NULL, ts_end INT NOT NULL,
    window_id TEXT REFERENCES capture_windows(id),
    source TEXT NOT NULL, speaker_ord INT, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY, ts INT NOT NULL, type TEXT NOT NULL,
    line TEXT NOT NULL, evidence TEXT, state TEXT DEFAULT 'shown'
);
CREATE INDEX IF NOT EXISTS ix_frames_ts ON frames(ts);
CREATE INDEX IF NOT EXISTS ix_frames_window ON frames(window_id);
CREATE INDEX IF NOT EXISTS ix_text_frame ON text_blocks(frame_id);
CREATE INDEX IF NOT EXISTS ix_audio_ts ON audio_segments(ts_start);
"""

# External-content FTS5: the index stores no copy of the text, triggers keep it
# in step with the base table. Same three triggers for each indexed table.
_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5(
    text, content='{tbl}', content_rowid='id', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS {tbl}_ai AFTER INSERT ON {tbl} BEGIN
    INSERT INTO {fts}(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS {tbl}_ad AFTER DELETE ON {tbl} BEGIN
    INSERT INTO {fts}({fts}, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS {tbl}_au AFTER UPDATE ON {tbl} BEGIN
    INSERT INTO {fts}({fts}, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO {fts}(rowid, text) VALUES (new.id, new.text);
END;
"""

INDEXED = (("text_blocks", "text_fts"), ("audio_segments", "audio_fts"))


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    """Thread-safe enough: one connection behind one lock.

    ponytail: single global write lock. Writes are a handful per second at most,
    so contention is not real yet. Split per-table or move to a writer thread only
    if a profile says the lock is the bottleneck.
    """

    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self.conn.executescript(SCHEMA)
            for tbl, fts in INDEXED:
                self.conn.executescript(_FTS.format(tbl=tbl, fts=fts))
            self.conn.commit()

    # --- writes ----------------------------------------------------------
    def _write(self, sql: str, args: Iterable[Any]) -> int:
        with self._lock:
            cur = self.conn.execute(sql, tuple(args))
            self.conn.commit()
            return cur.lastrowid

    def open_window(self, kind: str = "app", ts: int | None = None) -> str:
        wid = uuid.uuid4().hex
        self._write(
            "INSERT INTO capture_windows(id, opened_at, kind) VALUES (?,?,?)",
            (wid, ts or now_ms(), kind),
        )
        return wid

    def close_window(self, window_id: str, ts: int | None = None) -> None:
        self._write(
            "UPDATE capture_windows SET closed_at=? WHERE id=? AND closed_at IS NULL",
            (ts or now_ms(), window_id),
        )

    def add_frame(self, window_id, app, title, thumb_path=None, face_count=0, ts=None) -> int:
        return self._write(
            "INSERT INTO frames(ts, window_id, app, title, thumb_path, face_count)"
            " VALUES (?,?,?,?,?,?)",
            (ts or now_ms(), window_id, app, title, thumb_path, face_count),
        )

    def add_text(self, frame_id: int, source: str, text: str) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        return self._write(
            "INSERT INTO text_blocks(frame_id, source, text) VALUES (?,?,?)",
            (frame_id, source, text),
        )

    def add_audio(self, ts_start, ts_end, source, text, window_id=None, speaker_ord=None) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        return self._write(
            "INSERT INTO audio_segments(ts_start, ts_end, window_id, source, speaker_ord, text)"
            " VALUES (?,?,?,?,?,?)",
            (ts_start, ts_end, window_id, source, speaker_ord, text),
        )

    def add_card(self, type_: str, line: str, evidence: Any = None, ts=None, state="shown") -> int:
        return self._write(
            "INSERT INTO cards(ts, type, line, evidence, state) VALUES (?,?,?,?,?)",
            (ts or now_ms(), type_, line, json.dumps(evidence) if evidence is not None else None, state),
        )

    # --- reads -----------------------------------------------------------
    def search(self, query: str, limit: int = 30, since_ms: int = 0,
               until_ms: int = 1 << 62, snippet_tokens: int = 12) -> list[dict]:
        """Unified FTS across screen text and speech, best match first.

        `snippet_tokens` is small for the CLI; Jimmy asks for more so the model
        gets a sentence of context rather than a keyword.
        """
        n = max(1, min(64, int(snippet_tokens)))
        sql = f"""
        SELECT 'screen' AS kind, f.ts AS ts, f.app AS app, f.title AS title,
               t.source AS source, snippet(text_fts, 0, '[', ']', '...', {n}) AS snippet,
               bm25(text_fts) AS rank, f.thumb_path AS thumb_path
          FROM text_fts JOIN text_blocks t ON t.id = text_fts.rowid
                        JOIN frames f ON f.id = t.frame_id
         WHERE text_fts MATCH ? AND f.ts BETWEEN ? AND ?
        UNION ALL
        SELECT 'audio', a.ts_start, NULL, NULL, a.source,
               snippet(audio_fts, 0, '[', ']', '...', {n}), bm25(audio_fts), NULL
          FROM audio_fts JOIN audio_segments a ON a.id = audio_fts.rowid
         WHERE audio_fts MATCH ? AND a.ts_start BETWEEN ? AND ?
         ORDER BY rank LIMIT ?
        """
        args = (query, since_ms, until_ms, query, since_ms, until_ms, limit)
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args)]

    def activity(self, since_ms: int, until_ms: int, limit: int = 15) -> list[dict]:
        """Which app/title was on screen, when, and for how many captured frames."""
        sql = """SELECT app, title, MIN(ts) AS first_ts, MAX(ts) AS last_ts, COUNT(*) AS frames
                   FROM frames WHERE ts BETWEEN ? AND ?
                  GROUP BY app, title ORDER BY last_ts DESC LIMIT ?"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (since_ms, until_ms, limit))]

    def frame_times(self, since_ms: int, until_ms: int) -> list[int]:
        """Timestamps of every captured frame in a window, oldest first."""
        with self._lock:
            return [r[0] for r in self.conn.execute(
                "SELECT ts FROM frames WHERE ts BETWEEN ? AND ? ORDER BY ts", (since_ms, until_ms))]

    def speech(self, since_ms: int, until_ms: int, limit: int = 10) -> list[dict]:
        """Transcribed speech in a window, most recent first."""
        sql = """SELECT ts_start, source, text FROM audio_segments
                  WHERE ts_start BETWEEN ? AND ? ORDER BY ts_start DESC LIMIT ?"""
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, (since_ms, until_ms, limit))]

    def stats(self) -> dict:
        tables = ("capture_windows", "frames", "text_blocks", "audio_segments", "cards")
        with self._lock:
            out = {t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            row = self.conn.execute("SELECT MIN(ts), MAX(ts) FROM frames").fetchone()
        out["first_frame_ms"], out["last_frame_ms"] = row[0], row[1]
        return out

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
