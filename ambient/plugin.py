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
from .recall import hybrid

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_UNITS = {"min": 60, "minute": 60, "hour": 3600, "hr": 3600, "day": 86400}
_AGO_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "a few": 3, "a couple of": 2, "half a": 0.5, "half an": 0.5}


# A clock time: "10:40", "3pm", "3 p.m.", "11", "noon".
_T = r"(?:\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?|noon|midnight)"


def _minutes(tok: str) -> int | None:
    """Clock token -> minutes after midnight.

    ponytail: a bare hour from 1 to 7 is read as afternoon ("from 2 to 4"),
    since nobody asks what they were doing at 2 am. Say "2am" to mean it.
    """
    tok = tok.strip().replace(".", "").replace(" ", "")
    if tok == "noon":
        return 12 * 60
    if tok == "midnight":
        return 0
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", tok)
    if not m:
        return None
    h, mm, ap = int(m[1]), int(m[2] or 0), m[3]
    if h > 23 or mm > 59:
        return None
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 7:
        h += 12
    return h * 60 + mm


def _explicit(tok: str) -> bool:
    """Unmistakably a time, not just a number: "10:40", "3pm", "noon"."""
    return ":" in tok or bool(re.search(r"[ap]\.?m|noon|midnight", tok))


def clock_range(q: str) -> tuple[int, int, str] | None:
    """(start_min, end_min, label) for a clock time the question names, or None."""
    m = re.search(rf"\b(?:between|from)\s+({_T})\s*(?:and|to|till|until|-|–)\s*({_T})", q)
    if not m:
        d = re.search(rf"\b({_T})\s*(?:-|–)\s*({_T})", q)
        m = d if d and (_explicit(d[1]) or _explicit(d[2])) else None
    if m:
        a, b = _minutes(m[1]), _minutes(m[2])
        if a is not None and b is not None:
            if b <= a:
                b += 12 * 60          # "between 11 and 1" -> 11:00 to 13:00
            return a, min(b, 24 * 60), f"{m[1].strip()}–{m[2].strip()}"
    m = re.search(rf"\b(?:at|around|about|near)\s+({_T})", q)
    if m and _explicit(m[1]) and (a := _minutes(m[1])) is not None:
        return max(0, a - 15), min(24 * 60, a + 15), f"around {m[1].strip()}"
    m = re.search(rf"\b(?:after|since)\s+({_T})", q)
    if m and (a := _minutes(m[1])) is not None:
        return a, 24 * 60, f"after {m[1].strip()}"
    m = re.search(rf"\b(?:before|until|till)\s+({_T})", q)
    if m and (a := _minutes(m[1])) is not None:
        return 0, a, f"before {m[1].strip()}"
    return None


def _named_day(q: str, now: datetime, midnight: datetime) -> tuple[datetime, datetime, str] | None:
    if "yesterday" in q:
        return midnight - timedelta(days=1), midnight, "yesterday"
    if "this morning" in q:
        return midnight, midnight + timedelta(hours=12), "this morning"
    if "this afternoon" in q:
        return midnight + timedelta(hours=12), midnight + timedelta(hours=18), "this afternoon"
    if re.search(r"\b(?:this evening|tonight)\b", q):
        return midnight + timedelta(hours=18), midnight + timedelta(days=1), "this evening"
    if re.search(r"\btoday\b", q):
        return midnight, midnight + timedelta(days=1), "today"
    for i, day in enumerate(WEEKDAYS):
        if re.search(rf"\b{day}\b", q):
            back = (now.weekday() - i) % 7   # 0 = today; "Tuesday" on a Tuesday means today
            if back == 0 and re.search(rf"\blast {day}\b", q):
                back = 7                     # ...but "last Tuesday" on a Tuesday is a week ago
            start = midnight - timedelta(days=back)
            return start, start + timedelta(days=1), day.capitalize()
    return None


def time_window(question: str, now_ms: int) -> tuple[int, int, str] | None:
    """The time span a question names, as (since_ms, until_ms, label), or None.

    A day ("yesterday", "on Tuesday") and a clock time ("between 10:40 and
    11:10", "at 3pm", "after 11") combine; the clock narrows the day.

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
    if re.search(r"\b(?:last|past|this) month\b", q):
        return ms(midnight - timedelta(days=30)), now_ms, "last 30 days"
    # "an hour ago", "20 minutes ago", "2 days ago": around then, not since then (D31).
    m = re.search(r"\b(\d+|an?|one|two|three|four|five|a few|a couple of|half an?)\s+"
                  r"(min|minute|hour|hr|day)s?\s+ago\b", q)
    if m:
        n = float(m[1]) if m[1].isdigit() else _AGO_NUMS[m[1]]
        if m[2] == "day":
            start = midnight - timedelta(days=round(n))
            return ms(start), ms(start + timedelta(days=1)), m[0]
        span = n * _UNITS[m[2]]
        half = max(600, span * 0.35)
        return int(now_ms - (span + half) * 1000), int(min(now_ms, now_ms - (span - half) * 1000)), m[0]

    day = _named_day(q, now, midnight)
    clock = clock_range(q)
    if clock:
        base = day[0].replace(hour=0, minute=0) if day else midnight
        start, end = base + timedelta(minutes=clock[0]), base + timedelta(minutes=clock[1])
        label = f"{day[2]} {clock[2]}" if day else clock[2]
        if not day and ms(start) > now_ms:   # "at 3pm", asked at 11am: yesterday's 3pm
            start, end = start - timedelta(days=1), end - timedelta(days=1)
            label = f"yesterday {clock[2]}"
        return ms(start), min(now_ms, ms(end)), label
    if day:
        return ms(day[0]), min(now_ms, ms(day[1])), day[2]
    if re.search(r"\b(?:earlier|just now|recently|a (?:little )?while ago|a moment ago)\b", q):
        return now_ms - jcfg.DEFAULT_LOOKBACK_H * 3600_000, now_ms, "recently"
    return None


_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december")
_MON = r"(january|february|march|april|may|june|july|august|september|october|november|december|" \
       r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\b\.?"
_DATE = re.compile(rf"\b(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}|{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b|{_MON})"
                   r"(?:,?\s+(\d{4}))?")
_SPANS = {"day": 86400, "days": 86400, "week": 7 * 86400, "weeks": 7 * 86400, "month": 30 * 86400,
          "months": 30 * 86400, "year": 365 * 86400, "years": 365 * 86400}


def date_range(question: str, now_ms: int) -> tuple[int, int, str] | None:
    """A span of days or months to delete (D39), as (since_ms, until_ms, label):
    "September", "from September to October", "1 to 15 September", "25 Sep",
    "since September", "before 1 September", "older than 30 days", "everything",
    and every phrase `time_window` knows ("today", "last week", "on Tuesday").
    A month or day without a year is the most recent one that has begun."""
    q = question.lower()
    now = datetime.fromtimestamp(now_ms / 1000)
    ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731
    if m := re.search(r"\bolder than\s+(\d+|an?|one|two|three|four|five|six)\s+(days?|weeks?|months?|years?)\b", q):
        n = int(m[1]) if m[1].isdigit() else {**_AGO_NUMS, "six": 6}[m[1]]
        return 0, now_ms - int(n * _SPANS[m[2]] * 1000), f"older than {m[1]} {m[2]}"
    # "from 1 to 15 September" -> "1 September to 15 September"
    q = re.sub(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:to|till|until|-|–|and)\s*(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MON}",
               r"\1 \3 to \2 \3", q)
    spans = []
    for m in _DATE.finditer(q):
        day, mon = (m[1], m[2]) if m[2] else (m[4], m[3]) if m[3] else (None, m[5])
        if mon == "may" and not (day or m[6] or re.search(r"\b(?:in|from|since|before|of|to|until|during)\s+may\b", q)):
            continue                            # "may I ask", not the month
        mi =next(i for i, n in enumerate(_MONTH_NAMES) if n.startswith(mon.rstrip(".")[:3])) + 1
        year = int(m[6]) if m[6] else now.year
        try:
            start = datetime(year, mi, int(day) if day else 1)
        except ValueError:
            continue
        if not m[6] and start > now:
            start = start.replace(year=year - 1)
        end = (start + timedelta(days=1) if day else
               start.replace(year=start.year + (mi == 12), month=mi % 12 + 1))
        if not spans or spans[-1][0] != start:          # "September September": said twice, one month
            spans.append((start, end, start.strftime("%d %b %Y").lstrip("0") if day else start.strftime("%B %Y")))
    if len(spans) == 1:
        s, e, label = spans[0]
        if re.search(r"\b(?:since|after|onwards?|till now|until now|to now|to date)\b", q):
            return ms(s), now_ms, f"since {label}"
        if re.search(r"\b(?:before|until|till|up to)\b", q):
            return 0, ms(s), f"before {label}"
        return ms(s), min(now_ms, ms(e)), label
    if spans:
        return ms(spans[0][0]), min(now_ms, ms(spans[-1][1])), f"{spans[0][2]} to {spans[-1][2]}"
    if w := time_window(question, now_ms):
        return w
    if re.search(r"\b(?:everything|all (?:of )?(?:it|my data|the data|data|my history|history))\b", q):
        return 0, now_ms, "everything"
    return None


def coverage(times: list[int], since_ms: int, until_ms: int,
             gap_min: int = jcfg.COVERAGE_GAP_MIN) -> str:
    """Say plainly how much of a window was actually captured.

    Without this the model filled uncaptured stretches with plausible activity:
    it called 15 minutes with no captures "an active conversation". Gaps are
    unknown, and the context has to say so.
    """
    fmt = "%a %H:%M" if until_ms - since_ms > 20 * 3600_000 else "%H:%M"
    t = lambda x: datetime.fromtimestamp(x / 1000).strftime(fmt)  # noqa: E731
    if not times:
        return (f"No screen captures at all between {t(since_ms)} and {t(until_ms)}: "
                f"nothing is known about that period.")
    edges = [since_ms, *times, until_ms]
    gaps = [(a, b) for a, b in zip(edges, edges[1:]) if b - a >= gap_min * 60_000]
    head = f"{len(times)} screen captures between {t(since_ms)} and {t(until_ms)}."
    if not gaps:
        return head + " No gap longer than a few minutes."
    listed = ", ".join(f"{t(a)}–{t(b)}" for a, b in gaps[:6]) + (" and more" if len(gaps) > 6 else "")
    return (f"{head} Nothing was captured {listed} (away, an unchanged screen, or "
            f"capture off): treat those stretches as unknown.")


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

        # Keywords + meaning (Stage 5, D24), only when the question has a topic:
        # "what was I doing on Tuesday" has none, and meaning search would return
        # arbitrary nearest text; the activity timeline below answers that instead.
        if fts_query(question):
            for h in hybrid(store, question, since, until, jcfg.SEARCH_HITS):
                if h["ref"] > 0:
                    where = " — ".join(p for p in (h["app"], h["title"]) if p)
                    out.append(Snippet(h["ts"], f"screen · {where}", h["text"]))
                else:
                    out.append(Snippet(h["ts"], f"heard near {h['source']}", h["text"]))

        # A named time, or nothing matched by keyword: say what was going on then.
        if window or not out:
            a_since, a_until = (since, until) if window else (
                now_ms - jcfg.DEFAULT_LOOKBACK_H * 3600_000, now_ms)
            # Coverage goes first, so the context budget can never cut it off.
            out.insert(0, Snippet(None, "coverage",
                                  coverage(store.frame_times(a_since, a_until), a_since, a_until)))
            for a in store.activity(a_since, a_until):
                where = " — ".join(p for p in (a["app"], a["title"]) if p) or "unknown window"
                # First and last sighting, not a span: "10:21–11:23" read as an hour of use.
                seen = (f"seen once at {_hm(a['first_ts'])}" if a["frames"] == 1 else
                        f"first seen {_hm(a['first_ts'])}, last seen {_hm(a['last_ts'])}, "
                        f"{a['frames']} captures")
                out.append(Snippet(a["last_ts"], "activity", f"{where} ({seen})"))
            for s in store.speech(a_since, a_until):
                out.append(Snippet(s["ts_start"], f"heard near {s['source']}", s["text"]))
        return out

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None


def _hm(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M")
