"""How the day was spent, from frames already captured (D31). No new capture, no model.

Frames are written only when the screen changes (and, since D31, when you switch
to a window whose screen didn't), so time is estimated: each frame counts until
the next one, at most ACTIVE_GAP_S. A longer gap is away, paused, or a sensitive
surface, and counts as nothing. Good to the minute, not the second.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

from jimmy.memory import STOPWORDS

from . import config
from .db import Store
from .redact import is_own_window

NAMES = {"code": "VS Code", "msedge": "Edge", "ms-teams": "Teams", "explorer": "File Explorer",
         "windowsterminal": "Terminal", "applicationframehost": "Windows app",
         "snippingtool": "Snipping Tool", "searchhost": "Search", "powershell": "PowerShell"}

# Words of a usage question that aren't what it's about ("how long was I on *chrome*").
_USAGE_WORDS = set("""long much time spent spend spending screen apps app used use using hours
minutes many whole total usage breakdown most least which productive focused stats spent
overall where go went""".split())


def app_name(app: str | None) -> str:
    """'Code.exe' -> 'VS Code', 'chrome.exe' -> 'Chrome'."""
    base = re.sub(r"\.exe$", "", (app or "").replace("\\", "/").rsplit("/", 1)[-1], flags=re.I)
    return NAMES.get(base.lower()) or (base[:1].upper() + base[1:] if base else "Unknown")


def dur(ms: float) -> str:
    """Spoken-friendly: '1 hour 20 minutes', '35 minutes', 'under a minute'."""
    m = round(ms / 60_000)
    if m < 1:
        return "under a minute"
    h, m = divmod(m, 60)
    parts = ([f"{h} hour{'s' * (h != 1)}"] if h else []) + ([f"{m} minute{'s' * (m != 1)}"] if m else [])
    return " ".join(parts)


def pieces(frames: list[dict], until_ms: int) -> list[tuple[str, str, int, int]]:
    """(app name, title, start, end) per frame: until the next frame, at most ACTIVE_GAP_S."""
    cap = config.ACTIVE_GAP_S * 1000
    out = []
    for f, nxt in zip(frames, [*frames[1:], None]):
        end = min(nxt["ts"] if nxt else until_ms, f["ts"] + cap, until_ms)
        if end > f["ts"] and not is_own_window(f["app"], f["title"]):
            out.append((app_name(f["app"]), f["title"] or "", f["ts"], end))
    return out


def _hour_slices(a: int, b: int):
    """(local date, hour, ms) for a span, cut at hour boundaries."""
    t = a
    while t < b:
        d = datetime.fromtimestamp(t / 1000)
        nxt = int((d.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp() * 1000)
        yield d.strftime("%Y-%m-%d"), d.hour, min(b, nxt) - t
        t = min(b, nxt)


def summarize(ps: list[tuple[str, str, int, int]]) -> dict:
    """Totals, per app, per hour, contiguous runs, top titles, switches, longest run."""
    apps: dict[str, int] = defaultdict(int)
    titles: dict[tuple[str, str], int] = defaultdict(int)
    hours = [defaultdict(int) for _ in range(24)]
    runs: list[dict] = []
    for app, title, a, b in ps:
        apps[app] += b - a
        if title:
            titles[(app, title)] += b - a
        for _, h, ms in _hour_slices(a, b):
            hours[h][app] += ms
        if runs and runs[-1]["app"] == app and a - runs[-1]["end"] <= 1000:
            runs[-1]["end"] = b
        else:
            runs.append({"app": app, "start": a, "end": b})
    longest = max(runs, key=lambda r: r["end"] - r["start"], default=None)
    return {
        "active_ms": sum(apps.values()),
        "apps": [{"app": k, "ms": v} for k, v in sorted(apps.items(), key=lambda kv: -kv[1])],
        "hours": [dict(h) for h in hours],
        "runs": runs,
        "titles": [{"app": k[0], "title": k[1], "ms": v}
                   for k, v in sorted(titles.items(), key=lambda kv: -kv[1])[:8]],
        "switches": sum(1 for r0, r1 in zip(runs, runs[1:]) if r0["app"] != r1["app"]),
        "longest": longest and {**longest, "ms": longest["end"] - longest["start"]},
        "first": ps[0][2] if ps else None,
        "last": ps[-1][3] if ps else None,
    }


def _day_bounds(day: str) -> tuple[int, int]:
    start = datetime.strptime(day, "%Y-%m-%d")
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def day(store: Store, day_str: str | None = None, now: int | None = None) -> dict:
    """Everything the Insights view draws for one day, plus its week's heatmap."""
    now = now or int(time.time() * 1000)
    days = store.days()
    day_str = day_str or (days[0] if days else time.strftime("%Y-%m-%d"))
    since, until = _day_bounds(day_str)
    until = min(until, now)
    out = summarize(pieces(store.timeline(since, until), until))
    # The week ending on this day, hour by hour: one query, the same estimate.
    wk_since = since - 6 * 86_400_000
    grid: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    for _, _, a, b in pieces(store.timeline(wk_since, until), until):
        for d, h, ms in _hour_slices(a, b):
            grid[d][h] += ms
    week = []
    for i in range(7):
        d = datetime.fromtimestamp(wk_since / 1000) + timedelta(days=i)
        key = d.strftime("%Y-%m-%d")
        week.append({"day": key, "label": d.strftime("%a"), "hours": grid.get(key, [0] * 24)})
    return {**out, **store.tallies(since, until), "day": day_str, "days": days,
            "since": since, "until": until, "week": week, "gap_s": config.ACTIVE_GAP_S}


def answer(store: Store, question: str, window: tuple[int, int, str] | None,
           now: int) -> tuple[str, dict]:
    """A usage question, answered from captures in one short line + the data to draw.

    "how long was I on chrome today" -> the term is whatever word is left once
    question, time and usage words are gone; it matches app names and titles, so
    "youtube" finds a Chrome tab. With no term: the day's total and top apps.
    """
    if window is None:
        midnight = datetime.fromtimestamp(now / 1000).replace(hour=0, minute=0, second=0, microsecond=0)
        window = (int(midnight.timestamp() * 1000), now, "today")
    since, until, label = window
    ps = pieces(store.timeline(since, until), until)
    s = summarize(ps)
    when = _when(label)
    match = None
    for term in terms(question):
        hit = [(app, title, a, b) for app, title, a, b in ps if term in app.lower() or term in title.lower()]
        ms = sum(b - a for *_, a, b in hit)
        if match is None or ms > match["ms"]:
            # Spelled as seen: "youtube" -> "YouTube" from the tab title.
            name = next((app if term in app.lower() else re.search(re.escape(term), title, re.I)[0]
                         for app, title, *_ in hit), term.capitalize())
            match = {"term": term, "name": name, "ms": ms, "spans": [[a, b] for *_, a, b in hit]}
    if not ps:
        line = f"Nothing captured {when}."
    elif match and not match["ms"]:
        line = f"I didn't see {match['name']} {when}."
    elif match:
        line = f"{dur(match['ms'])} on {match['name']} {when}, of {dur(s['active_ms'])} on screen."
    else:
        top = s["apps"][:2]
        line = f"{dur(s['active_ms'])} on screen {when}. Most on {top[0]['app']} ({dur(top[0]['ms'])})"
        line += f", then {top[1]['app']} ({dur(top[1]['ms'])})." if len(top) > 1 else "."
    return line, {**s, "since": since, "until": until, "label": label, "match": match}


def terms(question: str) -> list[str]:
    """What a usage question is about, once question, time and usage words are gone."""
    return [w for w in re.findall(r"[a-z0-9][\w+#.-]*", question.lower())
            if len(w) > 1 and w not in STOPWORDS and w not in _USAGE_WORDS]


def _when(label: str) -> str:
    low = label.lower()
    if low in {d.lower() for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")}:
        return f"on {label}"
    return f"in the {label}" if low.startswith("last ") else label


if __name__ == "__main__":
    # One self-check: python -m ambient.insights
    s = Store(":memory:")
    w = s.open_window(ts=1)
    t0 = int(datetime(2026, 10, 2, 9, 0).timestamp() * 1000)
    for i, (app, title) in enumerate([("chrome.exe", "YouTube - Chrome"), ("chrome.exe", "Docs"),
                                      ("Code.exe", "x.py"), ("electron.exe", "Jimmy")]):
        s.add_frame(w, app, title, ts=t0 + i * 60_000)
    s.add_frame(w, "Code.exe", "x.py", ts=t0 + 30 * 60_000)        # 26 min after Jimmy: a gap
    ps = pieces(s.timeline(t0, t0 + 3600_000), t0 + 31 * 60_000)
    assert [p[0] for p in ps] == ["Chrome", "Chrome", "VS Code", "VS Code"], "own window skipped"
    sm = summarize(ps)
    assert sm["active_ms"] == 4 * 60_000 and sm["switches"] == 1 and len(sm["runs"]) == 3
    line, data = answer(s, "how long was I on youtube", (t0, t0 + 31 * 60_000, "today"), t0)
    assert line == "1 minute on YouTube today, of 4 minutes on screen." and data["match"]["ms"] == 60_000, line
    assert answer(s, "how long on slack", (t0, t0 + 31 * 60_000, "today"), t0)[0] == "I didn't see Slack today."
    print("ok  insights")
