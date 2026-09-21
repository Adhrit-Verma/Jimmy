"""The ambient layer as a Jimmy plugin (AMBIENT_LAYER.md Stage 2).

It gives Jimmy what was on screen and what was said, bounded by any time the
question names ("yesterday", "on Tuesday", "last 20 minutes"). It never talks to
a model: Jimmy owns the only LLM client, and a test scans this package's source
to make sure nothing in it references one.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from jimmy import config as jcfg
from jimmy.core import Snippet
from jimmy.memory import fts_query

from .db import Store

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_UNITS = {"min": 60, "minute": 60, "hour": 3600, "hr": 3600, "day": 86400}


def time_window(question: str, now_ms: int) -> tuple[int, int, str] | None:
    """The time span a question names, as (since_ms, until_ms, label), or None.

    ponytail: a handful of English phrases, not a date parser. "The 14th" or
    "last month" fall through to all-time search, which still works, just less
    precisely. Add phrases when real questions miss.
    """
    q = question.lower()
    now = datetime.fromtimestamp(now_ms / 1000)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731

    m = re.search(r"\b(?:last|past)\s+(\d+)\s*(min|minute|hour|hr|day)s?\b", q)
    if m:
        span = int(m.group(1)) * _UNITS[m.group(2)]
        return now_ms - span * 1000, now_ms, f"last {m.group(1)} {m.group(2)}s"
    if re.search(r"\b(?:last|past) hour\b", q):
        return now_ms - 3600_000, now_ms, "last hour"
    if re.search(r"\b(?:last|past|this) week\b", q):
        return ms(midnight - timedelta(days=7)), now_ms, "last 7 days"
    if "yesterday" in q:
        return ms(midnight - timedelta(days=1)), ms(midnight), "yesterday"
    if "this morning" in q:
        return ms(midnight), min(now_ms, ms(midnight + timedelta(hours=12))), "this morning"
    if "this afternoon" in q:
        return ms(midnight + timedelta(hours=12)), min(now_ms, ms(midnight + timedelta(hours=18))), "this afternoon"
    if re.search(r"\b(?:this evening|tonight)\b", q):
        return ms(midnight + timedelta(hours=18)), now_ms, "this evening"
    if re.search(r"\btoday\b", q):
        return ms(midnight), now_ms, "today"
    for i, day in enumerate(WEEKDAYS):
        if re.search(rf"\b{day}\b", q):
            back = (now.weekday() - i) % 7   # 0 = today; "Tuesday" on a Tuesday means today
            start = midnight - timedelta(days=back)
            return ms(start), min(now_ms, ms(start + timedelta(days=1))), day.capitalize()
    if re.search(r"\b(?:earlier|just now|recently|a (?:little )?while ago|a moment ago)\b", q):
        return now_ms - jcfg.DEFAULT_LOOKBACK_H * 3600_000, now_ms, "recently"
    return None


def _clean(snippet: str) -> str:
    return snippet.replace("[", "").replace("]", "")


class AmbientPlugin:
    name = "ambient"

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path) if str(db_path) != ":memory:" else db_path
        self._store: Store | None = None
        self.tools = {"search_captures": self.search_captures}

    def _db(self) -> Store | None:
        """Open lazily, and never create a capture DB from the reading side."""
        if self._store is None:
            if isinstance(self.db_path, Path) and not self.db_path.exists():
                return None
            self._store = Store(self.db_path)
        return self._store

    def search_captures(self, query: str, since_ms: int = 0, until_ms: int = 1 << 62,
                        limit: int = jcfg.SEARCH_HITS) -> list[dict]:
        store, q = self._db(), fts_query(query)
        if store is None or not q:
            return []
        return store.search(q, limit, since_ms, until_ms, jcfg.SNIPPET_TOKENS)

    def context(self, question: str, now_ms: int) -> list[Snippet]:
        store = self._db()
        if store is None:
            return []
        window = time_window(question, now_ms)
        since, until = (window[0], window[1]) if window else (0, now_ms)
        out: list[Snippet] = []

        for h in self.search_captures(question, since, until):
            if h["kind"] == "screen":
                where = " — ".join(p for p in (h["app"], h["title"]) if p)
                out.append(Snippet(h["ts"], f"screen · {where}", _clean(h["snippet"])))
            else:
                out.append(Snippet(h["ts"], f"speech · {h['source']}", _clean(h["snippet"])))

        # A named time, or nothing matched by keyword: say what was going on then.
        if window or not out:
            a_since, a_until = (since, until) if window else (
                now_ms - jcfg.DEFAULT_LOOKBACK_H * 3600_000, now_ms)
            for a in store.activity(a_since, a_until):
                span = f"{_hm(a['first_ts'])}–{_hm(a['last_ts'])}"
                where = " — ".join(p for p in (a["app"], a["title"]) if p) or "unknown window"
                out.append(Snippet(a["last_ts"], "activity",
                                   f"{where} (on screen {span}, {a['frames']} captures)"))
            for s in store.speech(a_since, a_until):
                out.append(Snippet(s["ts_start"], f"speech · {s['source']}", s["text"]))
        return out

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None


def _hm(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M")
