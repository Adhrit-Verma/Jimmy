"""Things Jimmy does on its own (D32).

Every one of these only touches Jimmy: it notices, and shows a card whose line
code writes from your own data. Anything that acts on the world, even setting
your focus, waits for your yes (non-negotiable 1). Driven by the bus's loop:

- RESUME:   back after a long gap -> "Left off: <what you were mostly on>"
- SUGGEST:  one window held most of the last 20 min and no focus set -> "Focus on …?"
- REMIND:   what you asked to be reminded of, at a time or when an app comes up
- DEADLINE: a date seen or heard that the local model agrees is a deadline ->
            "Tomorrow: …" the evening before, "Today: …" that morning
- RECAP:    once an evening, "Today: 5h 36m, mostly Chrome" (Sundays: the week)
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from jimmy import config as jcfg

from . import config, insights
from .db import Store
from .redact import is_own_window

HOUR, DAY = 3600_000, 86_400_000
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# Windows that say nothing about what you were doing.
_NEUTRAL = {"explorer.exe", "searchhost.exe", "lockapp.exe", "shellexperiencehost.exe",
            "applicationframehost.exe", "startmenuexperiencehost.exe", ""}


def _ms(d: datetime) -> int:
    return int(d.timestamp() * 1000)


def _midnight(ts: int) -> datetime:
    return datetime.fromtimestamp(ts / 1000).replace(hour=0, minute=0, second=0, microsecond=0)


def words(text: str, n: int) -> str:
    return " ".join(text.split()[:n])


def clean_title(title: str, app: str) -> str:
    """'main.py - proj - Visual Studio Code' -> 'main.py - proj'."""
    parts = [p.strip() for p in re.split(r"\s+[-—|·]\s+", title or "") if p.strip()]
    junk = {app.lower(), "google chrome", "microsoft edge", "visual studio code", "mozilla firefox",
            "microsoft teams", "discord", "chrome", "edge"}
    while len(parts) > 1 and any(j and j in parts[-1].lower() for j in junk):
        parts.pop()
    return " - ".join(parts)


def _main_window(store: Store, since: int, until: int) -> tuple[dict, float] | None:
    """The (app, title) with the most captures in a span, and its share of them."""
    acts = [a for a in store.activity(since, until, 30)
            if not is_own_window(a["app"], a["title"]) and (a["app"] or "").lower() not in _NEUTRAL and a["title"]]
    total = sum(a["frames"] for a in acts)
    if not acts or not total:
        return None
    top = max(acts, key=lambda a: a["frames"])
    return top, top["frames"] / total


def resume_card(store: Store, before_ts: int) -> tuple[str, dict] | None:
    """What you were mostly on in the half hour before a long gap."""
    got = _main_window(store, before_ts - 30 * 60_000, before_ts)
    if not got:
        return None
    top = got[0]
    name = insights.app_name(top["app"])
    frame = store.latest_frame(top["app"], top["title"], before_ts - 30 * 60_000, before_ts)
    return (f"Left off: {words(clean_title(top['title'], name), 4) or name}",
            {"at": top["last_ts"], "url": (frame or {}).get("url"), "why": f"{name}, until {_hm(top['last_ts'])}"})


def focus_offer(store: Store, now: int) -> str | None:
    """A focus worth offering: one window held most of the last few minutes."""
    got = _main_window(store, now - config.SUGGEST_FOCUS_WINDOW_S * 1000, now)
    if not got or got[1] < config.SUGGEST_FOCUS_SHARE or got[0]["frames"] < 8:
        return None
    name = insights.app_name(got[0]["app"])
    return words(clean_title(got[0]["title"], name), 5) or None


def recap_card(store: Store, now: int) -> tuple[str, dict] | None:
    d = datetime.fromtimestamp(now / 1000)
    midnight = _midnight(now)
    if d.hour < config.RECAP_HOUR or store.cards_since("RECAP", _ms(midnight)):
        return None
    week = d.weekday() == 6
    since = _ms(midnight - timedelta(days=6)) if week else _ms(midnight)
    s = insights.summarize(insights.pieces(store.timeline(since, now), now))
    if s["active_ms"] < config.RECAP_MIN_ACTIVE_S * 1000:
        return None
    return (f"{'This week' if week else 'Today'}: {_short(s['active_ms'])}, mostly {s['apps'][0]['app']}",
            {"view": "insights", "why": f"{s['switches']} app switches"})


# --- reminders ------------------------------------------------------------

_N = r"(\d+|an?|one|two|three|four|five|ten|fifteen|twenty|thirty|half an?)"
_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
         "fifteen": 15, "twenty": 20, "thirty": 30, "half a": 0.5, "half an": 0.5}


def parse_reminder(text: str, now: int) -> tuple[str, int | None, str | None]:
    """'remind me at 5 to call Sam' -> ('call Sam', <17:00 today>, None).
    'remind me to stretch when I open Discord' -> ('stretch', None, 'discord').
    The when is cut out; what's left is the reminder, in your words."""
    from .plugin import _T, _minutes
    t = re.sub(r"^\W*(?:please\s+)?remind me\s*", "", text.strip().rstrip(".!?"), flags=re.I)
    due = app = None
    base = datetime.fromtimestamp(now / 1000)
    midnight = _midnight(now)

    def cut(m):
        nonlocal t
        t = (t[:m.start()] + " " + t[m.end():]).strip()

    if m := re.search(rf"\bin\s+{_N}\s*(m|mins?|minutes?|h|hrs?|hours?)\b", t, re.I):
        n = float(m[1]) if m[1].isdigit() else _NUMS[m[1].lower()]
        due = now + int(n * (3600_000 if m[2][0].lower() == "h" else 60_000))
        cut(m)
    elif m := re.search(rf"\b(?:tomorrow|tmrw)(?:\s+(?:at|around|by)\s+({_T}))?\b", t, re.I):
        mins = _minutes(m[1]) if m[1] else 9 * 60
        due = _ms(midnight + timedelta(days=1, minutes=mins if mins is not None else 9 * 60))
        cut(m)
    elif m := re.search(rf"\b(?:at|around|by)\s+({_T})\b", t, re.I):
        mins = _minutes(m[1])
        if mins is not None:
            d = midnight + timedelta(minutes=mins)
            due = _ms(d if d > base else d + timedelta(days=1))
            cut(m)
    elif m := re.search(r"\b(tonight|this evening|this afternoon)\b", t, re.I):
        d = midnight + timedelta(hours=15 if "afternoon" in m[1].lower() else 20)
        due = _ms(d if d > base else base + timedelta(minutes=30))
        cut(m)
    if m := re.search(r"\bwhen(?:ever)? i (?:open|am on|am in|go to|get to|switch to|use|start)\s+([\w.+-]+(?: [\w.+-]+)?)",
                      t, re.I):
        app = m[1].lower().removesuffix(".exe")
        cut(m)
    what = re.sub(r"^(?:to|that|about)\s+|\s+(?:to)$", "", " ".join(t.split()), flags=re.I).strip()
    return what, due, app


# --- deadlines ------------------------------------------------------------

_DUE_WORDS = re.compile(r"\b(?:deadline|due|close[sd]?|closing|ends?|ending|expires?|expiring|last (?:date|day)|"
                        r"submit|submission|apply|register|registration|before|until|interview|meeting|"
                        r"appointment|exam|starts?|webinar|call)\b", re.I)
_DATE_RX = [
    ("rel", re.compile(r"\b(today|tonight|tomorrow)\b", re.I)),
    ("dow", re.compile(r"\b(?:on\s+|this\s+|next\s+)?(" + "|".join(WEEKDAYS) + r")\b", re.I)),
    ("dmy", re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")[a-z]*\.?,?(?:\s+(\d{4}))?\b", re.I)),
    ("mdy", re.compile(r"\b(" + "|".join(MONTHS) + r")[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b,?(?:\s+(\d{4}))?", re.I)),
    ("iso", re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")),
    ("num", re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")),   # DD/MM/YYYY, as written in India
]
_TIME_RX = re.compile(r"\b(?:at|by|before|from)\s+(\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)|\d{1,2}:\d{2})", re.I)


def parse_due(text: str, seen_ts: int) -> tuple[int, bool, tuple[int, int]] | None:
    """(due ms, has a time, span of the date words) for the first date in `text`
    that is today or later (relative to when it was seen), within DEADLINE_MAX_DAYS."""
    from .plugin import _minutes
    seen = _midnight(seen_ts)
    for kind, rx in _DATE_RX:
        m = rx.search(text)
        if not m:
            continue
        try:
            if kind == "rel":
                day = seen + timedelta(days=1 if m[1].lower() == "tomorrow" else 0)
            elif kind == "dow":
                day = seen + timedelta(days=(WEEKDAYS.index(m[1].lower()) - seen.weekday()) % 7)
            elif kind in ("dmy", "mdy"):
                d, mon, y = (m[1], m[2], m[3]) if kind == "dmy" else (m[2], m[1], m[3])
                day = datetime(int(y or seen.year), MONTHS.index(mon[:3].lower()) + 1, int(d))
                if not y and day < seen - timedelta(days=1):
                    day = day.replace(year=day.year + 1)
            elif kind == "iso":
                day = datetime(int(m[1]), int(m[2]), int(m[3]))
            else:
                day = datetime(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            continue
        if not (seen <= day <= seen + timedelta(days=config.DEADLINE_MAX_DAYS)):
            return None
        t = _TIME_RX.search(text)
        mins = _minutes(t[1]) if t else None
        due = day + timedelta(minutes=mins) if mins is not None else day + timedelta(hours=23, minutes=59)
        return _ms(due), mins is not None, m.span()
    return None


def deadline_subject(text: str, span: tuple[int, int]) -> str:
    """The words around a date, without it: 'Applications close on Monday' -> 'Applications close'."""
    rest = text[:span[0]] + " " + text[span[1]:]
    rest = _TIME_RX.sub(" ", rest)
    rest = re.sub(r"\b(?:on|by|before|until|at|the|is|are|will|be)\s*$", "", " ".join(rest.split()), flags=re.I)
    rest = re.sub(r"^\W+|\W+$", "", rest)
    return words(rest, 4)


def deadline_key(text: str, due_ts: int) -> str:
    norm = " ".join(re.findall(r"[a-z0-9]+", text.lower()))[:80]
    return f"{time.strftime('%Y-%m-%d', time.localtime(due_ts / 1000))}|{norm}"


def find_deadlines(rows: list[dict], is_deadline: Callable[[str], bool | None], junk: frozenset,
                   store: Store, budget: list[int]) -> int:
    """Scan new text for deadline lines; the local model has the last word. Returns found."""
    found = 0
    for r in rows:
        for line in (ln.strip() for ln in r["text"].split("\n")):
            if not (12 <= len(line) <= 240) or line in junk or not _DUE_WORDS.search(line):
                continue
            got = parse_due(line, r["ts"])
            if not got:
                continue
            key = deadline_key(line, got[0])
            if store.has_deadline(key) or budget[0] <= 0:
                continue
            budget[0] -= 1
            if is_deadline(line):
                found += store.add_deadline(r["ts"], got[0], line, key, r["ref"])
    return found


def deadline_cards(store: Store, now: int) -> list[tuple[int, str, str, dict]]:
    """(deadline id, new state, line, payload) for warnings due now: the evening
    before ("Tomorrow: …") and the morning of ("Today: …")."""
    today = _midnight(now)
    hour = datetime.fromtimestamp(now / 1000).hour
    out = []
    for d in store.deadlines(_ms(today), _ms(today + timedelta(days=2))):
        due_day = _midnight(d["due_ts"])
        span = parse_due(d["text"], d["seen_ts"])
        subject = deadline_subject(d["text"], span[2]) if span else words(d["text"], 4)
        at = f" {_hm(d['due_ts'])}" if span and span[1] else ""
        payload = {"at": d["seen_ts"], "why": d["text"][:160]}
        if due_day == today + timedelta(days=1) and hour >= config.DEADLINE_EVE_HOUR and d["state"] == "new":
            out.append((d["id"], "eve", f"Tomorrow{at}: {subject}", payload))
        elif due_day == today and hour >= 7 and d["state"] in ("new", "eve"):
            out.append((d["id"], "day", f"Today{at}: {subject}", payload))
    return out


# --- calendar files ---------------------------------------------------------

def calendar_file(ev: dict, folder: Path | None = None) -> Path:
    """An .ics for one event the user confirmed. Opening it hands it to their own
    calendar app, which asks once more before saving: Jimmy never adds it itself."""
    esc = lambda s: re.sub(r"([,;\\])", r"\\\1", str(s)).replace("\n", "\\n")  # noqa: E731
    day = datetime.strptime(ev["date"], "%Y-%m-%d")
    if ev.get("start"):
        start = day + timedelta(hours=int(ev["start"][:2]), minutes=int(ev["start"][3:5]))
        end = (day + timedelta(hours=int(ev["end"][:2]), minutes=int(ev["end"][3:5]))
               if ev.get("end") else start + timedelta(hours=1))
        when = [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{end:%Y%m%dT%H%M%S}"]
    else:
        when = [f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Jimmy//EN", "BEGIN:VEVENT",
             f"UID:{uuid.uuid4().hex}@jimmy", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", *when,
             f"SUMMARY:{esc(ev['title'])}"] + ([f"LOCATION:{esc(ev['where'])}"] if ev.get("where") else []) + \
            ["END:VEVENT", "END:VCALENDAR"]
    folder = folder or config.DATA_DIR / "events"
    folder.mkdir(parents=True, exist_ok=True)
    slug = "-".join(re.findall(r"[a-z0-9]+", ev["title"].lower()))[:40] or "event"
    path = folder / f"{ev['date']}-{slug}.ics"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def valid_event(ev: dict | None) -> dict | None:
    """The model's extraction, checked by code: a real date, real times, a title."""
    if not ev or not str(ev.get("title", "")).strip():
        return None
    try:
        datetime.strptime(str(ev.get("date", "")), "%Y-%m-%d")
        for k in ("start", "end"):
            if ev.get(k) and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(ev[k])):
                ev[k] = ""
    except ValueError:
        return None
    return {"title": " ".join(str(ev["title"]).split())[:80], "date": ev["date"],
            "start": ev.get("start") or "", "end": ev.get("end") or "",
            "where": " ".join(str(ev.get("where") or "").split())[:120]}


def _hm(ts: int) -> str:
    return time.strftime("%H:%M", time.localtime(ts / 1000))


def _short(ms: int) -> str:
    m = round(ms / 60_000)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


class Proactive:
    """Runs the checks above on the bus's clock. `show(kind, line, payload)` puts a
    card up (the bus stores it and applies what you've muted); `offer(kind, data)`
    tells the Asker a "yes" now means something; `say` reads reminders aloud."""

    def __init__(self, store: Store, memory, show: Callable[[str, str, dict], None],
                 offer: Callable[[str, object], None] = lambda k, d: None,
                 say: Callable[[str], None] | None = None,
                 is_deadline: Callable[[str], bool | None] | None = None):
        self.store, self.memory, self.show, self.offer, self.say = store, memory, show, offer, say
        self.is_deadline = is_deadline
        self._last: dict[str, int] = {}
        self._scan_ids = store.last_ids()       # deadlines: only text from now on
        self._scanning = False
        self._budget = [config.DEADLINE_CHECKS_PER_HOUR, 0]

    def _due(self, name: str, every_s: float, now: int) -> bool:
        if now - self._last.get(name, 0) < every_s * 1000:
            return False
        self._last[name] = now
        return True

    def on_capture(self, ts: int, prev_ts: int | None) -> None:
        """A frame was written; `prev_ts` is the one before it."""
        if prev_ts and ts - prev_ts >= config.RESUME_GAP_S * 1000:
            card = resume_card(self.store, prev_ts)
            if card:
                self.show("RESUME", *card)

    def tick(self, now: int, app: str = "", title: str = "", quiet: bool = False) -> None:
        """`quiet` (D39): you're away and Jimmy rests: reminders and timers only."""
        if self.memory is not None:
            for r in self.memory.due_reminders(now, f"{insights.app_name(app)} {title}" if app else None):
                self.memory.set_reminder_state(r["id"], "done")
                self.show("REMIND", words(r["text"], 10), {"why": "you asked"})
                if self.say:
                    self.say(f"Time's up: {r['text']}." if r["text"].endswith("timer") else f"Reminder: {r['text']}")
        if quiet or not self._due("minute", 60, now):
            return
        if card := recap_card(self.store, now):
            self.show("RECAP", *card)
        for did, state, line, payload in deadline_cards(self.store, now):
            self.store.set_deadline_state(did, state)
            self.show("DEADLINE", line, payload)
        if (self.memory is not None and not self.memory.current_intent(jcfg.FOCUS_INTENT_MAX_H, now)
                and now - self._last.get("offer", 0) >= config.SUGGEST_FOCUS_EVERY_S * 1000
                and (focus := focus_offer(self.store, now))):
            self._last["offer"] = now
            self.offer("focus", focus)
            self.show("SUGGEST", f"Focus on {focus}?", {"focus": focus, "why": "most of the last 20 minutes"})
        if self.is_deadline and not self._scanning and self._due("scan", config.DEADLINE_SCAN_S, now):
            self._scanning = True
            threading.Thread(target=self._scan, args=(now,), daemon=True, name="deadlines").start()

    def _scan(self, now: int) -> None:
        try:
            if now - self._budget[1] >= HOUR:
                self._budget = [config.DEADLINE_CHECKS_PER_HOUR, now]
            rows, b, a = self.store.new_text(*self._scan_ids)
            self._scan_ids = (b, a)
            from .recall import furniture
            n = find_deadlines(rows, self.is_deadline, furniture(self.store), self.store, self._budget)
            if n:
                print(f"[deadlines] {n} new")
        except Exception as exc:                    # never take the loop down
            print(f"[deadlines] {type(exc).__name__}: {exc}")
        finally:
            self._scanning = False
