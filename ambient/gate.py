"""Tier 1 of the trigger gate: local rules, no LLM (Stage 3, D19).

This decides *whether anything is worth a look*. Tier 2 (jimmy/cards.py) then
decides whether to speak. The same class runs live (fed by the bus) and in
replay (fed from the store), so replay tunes exactly what runs live.

Rules:
- RECALL after a moment: a *moment* is a stretch in one window (app + title).
  When it ends, if it was substantial, take its distinctive words (rare across
  all earlier text) and look for an earlier moment elsewhere, at least
  RECALL_MIN_AGE_S old, sharing RECALL_MIN_SHARED of them. The spec: RECALL
  "fires after a moment ends, not during it".
- RECALL on a question heard aloud: the same lookup, from the question's words.
- FOCUS on drift: only if the user stated an intent (`jimmy focus "..."`), and
  every window for FOCUS_DRIFT_S has been unrelated to it. Once per drift.
- Hard limits before any cloud call: a rolling-hour card cap, a minimum gap
  between cards, a candidate cap, no repeats, and a cooldown after dismissal.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable

from jimmy import config as jcfg
from jimmy.cards import Candidate, Card, CardEngine
from jimmy.memory import STOPWORDS, Memory

from . import config
from .db import Store

_WORD = re.compile(r"[a-z][a-z0-9'-]{3,}")   # 4+ chars: shorter words are rarely distinctive
HOUR = 3600_000


# Words that are everywhere in a working day. Word rarity (term_share) should
# catch them, but only once there's plenty of history: the first 71-minute
# replay matched moments on "open/close", "file/python", "forward/enter".
GENERIC = set("""
open close file files folder enter forward back next previous press click type
think follow reply replied response responded message messages send sent chat
view page home help show hide start stop edit save copy paste delete select search
settings account profile menu window screen button link tab tabs new update updated
time today yesterday tomorrow week like know want need make made going right good
okay yeah thing things people work working user users name python code error
""".split())


def words(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip("'-")
        if w not in STOPWORDS and w not in GENERIC:
            out.append(w)
    return out


def stems(terms: list[str]) -> set[str]:
    """Crude stemming so "responded"/"response" count once. ponytail: 6-char
    prefix, not a real stemmer; good enough to stop one idea counting twice."""
    return {t[:6] for t in terms}


def is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") and len(t.split()) >= 4


@dataclass
class Moment:
    app: str
    title: str
    window_id: str | None
    start: int
    last: int
    text: list[str] = field(default_factory=list)
    speech: list[str] = field(default_factory=list)

    def body(self) -> str:
        return "\n".join(self.text + self.speech)


class Gate:
    def __init__(self, store: Store, engine: CardEngine | None, memory: Memory | None = None,
                 on_card: Callable[[Card], None] | None = None,
                 on_decision: Callable[[Candidate, Card | None, str], None] | None = None,
                 intent: str | None = None, background: bool = False,
                 history_until: int | None = None):
        self.store, self.engine, self.memory = store, engine, memory
        # line -> capture windows it has appeared in. A line seen in several
        # windows is screen furniture (sidebar, friend list, own name, buttons),
        # not content (D22). Built only from the past: live loads history up to
        # now; replay starts empty and learns as it goes, so there's no look-ahead.
        # ponytail: an in-memory map, fine for weeks of history; move it to a SQL
        # table if months make start-up slow.
        self.line_windows: dict[str, set] = defaultdict(set)
        if history_until:
            for wid, text in store.blocks_before(history_until):
                self._learn_lines(wid, text)
        self.on_card = on_card or (lambda c: None)
        self.on_decision = on_decision or (lambda cand, card, why: None)
        self.intent_override = intent   # replay: pretend this intent held throughout
        self.moment: Moment | None = None
        self.cards: deque[int] = deque()
        self.cands: deque[int] = deque()
        self.used: set[str] = set()
        self.cooldown_until = 0
        self.off_since: int | None = None
        self.focus_fired = False
        self.last_focus_card = 0
        self.recent: deque[tuple[int, str, str]] = deque(maxlen=12)
        self.stats: Counter = Counter()
        self._lock = threading.RLock()
        self._q: queue.Queue | None = None
        if background:
            self._q = queue.Queue(maxsize=32)
            threading.Thread(target=self._drain, daemon=True, name="gate-tier2").start()

    # --- inputs -------------------------------------------------------------
    def observe_frame(self, ts: int, app: str, title: str, window_id: str | None, text: str) -> None:
        with self._lock:
            m = self.moment
            if m and (app, title) != (m.app, m.title):
                self._end_moment(m, ts)
                m = None
            if m is None:
                self.moment = m = Moment(app, title, window_id, ts, ts)
                self.recent.append((ts, app, title))
            m.last = ts
            if text:
                m.text.append(text)
                self._learn_lines(window_id, text)
            self._focus(ts, app, title, text)

    def _learn_lines(self, window_id: str | None, text: str) -> None:
        for line in text.split("\n"):
            line = line.strip()
            if line:
                self.line_windows[line].add(window_id)

    def content(self, text: str) -> str:
        """`text` minus screen furniture: lines already seen in several windows."""
        return "\n".join(ln for ln in (x.strip() for x in text.split("\n")) if ln and
                         len(self.line_windows.get(ln, ())) < config.PERSISTENT_LINE_WINDOWS)

    def observe_speech(self, ts_start: int, ts_end: int, source: str, text: str) -> None:
        with self._lock:
            if self.moment:
                self.moment.speech.append(text)
            if is_question(text):
                self.stats["question_heard"] += 1
                self._recall(terms_from=text, now=f"Heard near the {source}: {text}",
                             ts=ts_end, before=ts_start - 10 * 60_000, exclude_window=None,
                             reason="question heard aloud")

    def flush(self, ts: int) -> None:
        with self._lock:
            if self.moment:
                self._end_moment(self.moment, ts)
                self.moment = None

    def dismissed(self, ts: int) -> None:
        """A card was waved away: stay quiet for a while (wired by Stage 4's overlay)."""
        with self._lock:
            self.cooldown_until = ts + config.DISMISS_COOLDOWN_S * 1000

    def close(self) -> None:
        if self._q is not None:
            self._q.put(None)

    # --- rules --------------------------------------------------------------
    def _end_moment(self, m: Moment, end: int) -> None:
        # Only content counts: a moment of pure sidebar is not a moment (D22).
        body = "\n".join([self.content("\n".join(m.text))] + m.speech).strip()
        if (end - m.start) / 1000 < config.MOMENT_MIN_S or len(body) < config.MOMENT_MIN_CHARS:
            self.stats["moment_too_small"] += 1
            return
        self.stats["moment_ended"] += 1
        self._recall(terms_from=f"{m.title}\n{body}", now=f"{m.app} — {m.title}\n{body}",
                     ts=end, before=m.start - config.RECALL_MIN_AGE_S * 1000,
                     exclude_window=m.window_id, reason="moment ended")

    def _distinctive(self, text: str, until: int) -> list[str]:
        out: list[str] = []
        for w, _ in Counter(words(text)).most_common(config.RECALL_TERMS * 4):
            if w.isdigit():
                continue
            share = self.store.term_share(w, until)
            # Seen before (or nothing can match) but rare (or it matches everything).
            if 0 < share <= config.RECALL_MAX_TERM_SHARE:
                out.append(w)
            if len(out) >= config.RECALL_TERMS:
                break
        return out

    def _recall(self, terms_from: str, now: str, ts: int, before: int,
                exclude_window: str | None, reason: str) -> None:
        if before <= 0:
            return
        terms = self._distinctive(terms_from, before)
        if len(stems(terms)) < config.RECALL_MIN_SHARED:
            self.stats["recall_few_terms"] += 1
            return
        hits = self.store.search(" OR ".join(f'"{t}"' for t in terms), 15, 0, before, 48)
        good = []
        for h in hits:
            if exclude_window and h["window_id"] == exclude_window:
                continue
            # Match on the earlier item's content only, never its furniture: the
            # "resume" match was a chat title in an always-visible sidebar (D22).
            body = self.content(self.store.block_text(h["ref"]))
            shared = [t for t in terms if t in body.lower()]
            if len(stems(shared)) >= config.RECALL_MIN_SHARED and f"recall:{h['ref']}" not in self.used:
                good.append((h, shared, body))
        if not good:
            self.stats["recall_no_match"] += 1
            return
        h, shared, _ = good[0]
        evidence = [{"ts": g["ts"], "text": body[:400],
                     "where": " — ".join(p for p in (g["app"], g["title"]) if p)
                     or f"heard near {g['source']}"} for g, _, body in good[:3]]
        self._submit(Candidate("RECALL", ts, f"{reason}; shares {', '.join(shared)}",
                               now, evidence, f"recall:{h['ref']}"))

    def _focus(self, ts: int, app: str, title: str, text: str) -> None:
        intent = self.intent_override or (
            (self.memory.current_intent(jcfg.FOCUS_INTENT_MAX_H, ts) or {}).get("text")
            if self.memory else None)
        if not intent:
            self.off_since, self.focus_fired = None, False
            return
        goal = set(words(intent))
        if app.lower() in config.FOCUS_NEUTRAL_APPS or goal & set(words(f"{app} {title} {text}")):
            self.off_since, self.focus_fired = None, False
            return
        self.off_since = self.off_since or ts
        if self.focus_fired or ts - self.off_since < config.FOCUS_DRIFT_S * 1000:
            return
        if ts - self.last_focus_card < config.FOCUS_REPEAT_S * 1000:
            self.stats["focus_repeat_held"] += 1
            return
        self.focus_fired = True
        seen = [{"ts": t, "where": a, "text": ti} for t, a, ti in self.recent if t >= self.off_since]
        self._submit(Candidate(
            "FOCUS", ts, f"nothing related to the stated intent since "
            f"{time.strftime('%H:%M', time.localtime(self.off_since / 1000))}: "
            f"{(ts - self.off_since) // 60000} min, threshold {config.FOCUS_DRIFT_S // 60} min",
            f"Stated intent: {intent}\nNow: {app} — {title}",
            [{"ts": None, "where": "stated intent", "text": intent}, *seen[-5:]],
            f"focus:{self.off_since}"))

    # --- limits and Tier 2 --------------------------------------------------
    def _card_blocked(self, ts: int) -> str | None:
        while self.cards and ts - self.cards[0] > HOUR:
            self.cards.popleft()
        if ts < self.cooldown_until:
            return "cooldown after dismissal"
        if len(self.cards) >= config.MAX_CARDS_PER_HOUR:
            return "hourly card cap"
        if self.cards and ts - self.cards[-1] < config.MIN_CARD_GAP_S * 1000:
            return "too soon after the last card"
        return None

    def _submit(self, cand: Candidate) -> None:
        while self.cands and cand.ts - self.cands[0] > HOUR:
            self.cands.popleft()
        blocked = self._card_blocked(cand.ts) or (
            "already considered" if cand.key in self.used else None) or (
            "hourly candidate cap" if len(self.cands) >= config.MAX_CANDIDATES_PER_HOUR else None)
        if blocked:
            self.stats[f"blocked: {blocked}"] += 1
            self.on_decision(cand, None, f"blocked: {blocked}")
            return
        self.used.add(cand.key)        # asked once, whatever the answer
        self.cands.append(cand.ts)
        self.stats[f"candidate {cand.type}"] += 1
        if self._q is not None:
            try:
                self._q.put_nowait(cand)
            except queue.Full:
                self.stats["blocked: tier 2 busy"] += 1
        else:
            self._decide(cand)

    def _decide(self, cand: Candidate) -> None:
        if self.engine is None:
            self.on_decision(cand, None, "dry run: Tier 2 not called")
            return
        card, why = self.engine.decide(cand)
        with self._lock:
            blocked = self._card_blocked(cand.ts) if card else None
            if card and not blocked:
                self.cards.append(cand.ts)
                if card.type == "FOCUS":
                    self.last_focus_card = cand.ts
                self.stats[f"card {card.type}"] += 1
                self.on_card(card)
            elif card:
                card, why = None, f"blocked after decision: {blocked}"
            else:
                self.stats["silence"] += 1
        self.on_decision(cand, card, why)

    def _drain(self) -> None:
        while (cand := self._q.get()) is not None:
            try:
                self._decide(cand)
            except Exception as exc:  # Tier 2 failing must never stop capture
                self.stats["tier 2 error"] += 1
                self.on_decision(cand, None, f"error: {type(exc).__name__}: {exc}")


def replay(store: Store, since_ms: int, until_ms: int, engine: CardEngine | None,
           memory: Memory | None = None, intent: str | None = None) -> dict:
    """Run the live gate over stored history, in time order, with no look-ahead.

    Search and word-rarity are always bounded to before the moment in question,
    so a replayed card could have been produced live.
    """
    decisions: list[tuple[Candidate, Card | None, str]] = []
    cards: list[Card] = []
    gate = Gate(store, engine, memory, on_card=cards.append, history_until=since_ms or None,
                on_decision=lambda c, k, w: decisions.append((c, k, w)), intent=intent)
    events = store.events(since_ms, until_ms)
    for ev in events:
        if ev["kind"] == "frame":
            gate.observe_frame(ev["ts"], ev["app"] or "", ev["title"] or "", ev["window_id"], ev["text"])
        else:
            gate.observe_speech(ev["ts"], ev["ts_end"], ev["source"], ev["text"])
    if events:
        gate.flush(events[-1]["ts_end"])
    # Covered time = the span of each session (gaps > 20 min split sessions).
    covered, prev, start = 0, None, None
    for ev in events:
        t = ev["ts_end"]
        if prev is None or t - prev > 20 * 60_000:
            if prev is not None:
                covered += prev - start
            start = t
        prev = t
    if prev is not None:
        covered += prev - start
    worst = max((sum(1 for d in cards if 0 <= d.ts - c.ts < HOUR) for c in cards), default=0)
    return {"events": len(events), "hours": covered / HOUR, "cards": cards,
            "decisions": decisions, "worst_hour": worst, "stats": dict(gate.stats)}

