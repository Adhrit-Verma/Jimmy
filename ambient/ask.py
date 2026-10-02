"""Ask Jimmy by voice; the answer comes to you (D25, D27).

Say "Jimmy, …" and the mic's live transcription (already running) hands the rest
to the Asker, which first decides what kind of question it is (D27):

- chat:   talking to Jimmy ("can you hear me?", "thanks", "what can you do?")
          → a natural reply, no evidence panel;
- screen: about what's in front of you now ("what's on my screen", "summarise
          this page") → answered from the window you're on, shown large;
- recall: about the past → hybrid search across days, evidence on the left.

Questions within CONVO_S of each other are one conversation: short follow-ups
("and when does it close?") carry the last topic into the search, and Jimmy sees
the recent turns. Answers are read aloud with Windows' built-in voice (SAPI). The
mic pauses while Jimmy speaks, and commands to Jimmy are never evidence.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from typing import Callable

from jimmy import config as jcfg
from jimmy.core import LLMError, Snippet
from jimmy.memory import fts_query

from . import config, insights
from .db import Store, now_ms
from .recall import furniture, hybrid
from .redact import is_own_window

# Whisper spells the name a few ways; the question follows the name.
_WAKE = re.compile(r"^\W*(?:(?:hey|hi|ok|okay|yo)\W+)?(?:jimmy|jimmie|jimi|jimmi|jimy)\b\W*(.*)$",
                   re.I | re.S)

# --- routing (D27): plain rules, deterministic and testable ------------------
_SCREEN = re.compile(
    r"\b(?:on|in) (?:my|the|this) (?:screen|window|page|tab)\b"
    r"|\bwhat(?:'s| is) (?:this|that) (?:page|window|tab|site|document|file)\b"
    r"|\bwhat(?: am i|'m i| i'm) (?:looking at|reading|seeing|watching|doing)(?: right)? now\b"
    r"|\b(?:summari[sz]e|explain|read|describe) (?:this|the page|the screen|my screen|what'?s on)\b"
    r"|\bwhat(?:'s| is) on (?:my |the )?screen\b", re.I)
_CHAT = re.compile(
    r"^(?:can|could|do|are|will) you (?:hear|listen|there|awake|working|understand|see me)\b"
    r"|^(?:hi|hello|hey|thanks|thank you|thank|good (?:morning|afternoon|evening|night)|bye|ok|okay)\b"
    r"|\bwho are you\b|\bwhat can you do\b|\bhow are you\b|\bwhat(?:'s| is) your name\b", re.I)
_PAST = re.compile(
    r"\b(?:saw|seen|was|were|did|had|heard|said|told|earlier|yesterday|before|last|ago|remember|"
    r"find|look(?:ed)? up|which|when did|where did|who was|opened|read|watched|wrote|typed)\b", re.I)
_FOLLOW = re.compile(r"^(?:and|also|so|then|what about|how about|and what|but)\b"
                     r"|\b(?:it|that|this|those|these|they|them|there|then|he|she)\b", re.I)
# D28: the screen *now* vs a screen captured earlier. Jimmy asks when it can't tell.
_SCREEN_WORD = re.compile(r"\b(?:screen|window|page|tab|site|document)\b", re.I)
_DEICTIC = re.compile(r"^(?:what(?:'s| is)|tell me (?:more )?about|explain|who(?:'s| is))\s+"
                      r"(?:this|that|it)\b(?:\s+\w+){0,3}\s*\??$", re.I)
# "What's this?" and nothing more: "this" points at what's in front of you, so even
# mid-conversation it may mean the screen. Ask, unless we were just on the screen.
_BARE_THIS = re.compile(r"^(?:what(?:'s| is)|explain|tell me about)\s+this\s*\??$", re.I)
_NOW = re.compile(r"\b(?:now|right now|currently|current|at the moment|in front of me|open now|"
                  r"this one|on (?:my|the) screen)\b", re.I)
_SHOW = re.compile(r"\b(?:show|open|zoom|enlarge|bigger)\b.*\b(?:first|best|top|second|third|one|it|that|match)\b"
                   r"|\b(?:show|zoom|open)(?: it| that)?(?: bigger| bigger please)?$", re.I)
_ORDINAL = {"first": 0, "best": 0, "top": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4, "last": -1}
CLARIFY_Q = "Your screen right now, or something from earlier?"

# D31: how the day went, answered from captures in code (no model, instant).
_STATS = re.compile(
    r"\bhow (?:long|much time|many (?:hours|minutes))\s+(?:was i|did i|have i|i)\b(?!.*\bago\b)"
    r"|\bscreen ?time\b|\btime (?:spent|on screen)\b|\bspen[dt] (?:my |the )?(?:time|day|morning|afternoon)\b"
    r"|\b(?:which|what) apps? (?:did i use|have i used|was i (?:on|using)|i used)\b|\bmost used apps?\b"
    r"|\b(?:show|how was|how'?s|recap|review)\s+(?:me\s+)?my (?:day|week|morning|afternoon|evening)\b"
    r"|\bwhere did (?:my |the )?(?:time|day) go\b|\bhow (?:productive|focused) was i\b", re.I)
# Only these continue a usage answer; "what is this?" after one is a new question.
_STATS_FOLLOW = re.compile(r"(?:and|also|what about|how about|and what about)\b", re.I)

# D31: things to do, not questions. Only ever from the user's own mic or typing.
_NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
         "fifteen": 15, "twenty": 20, "thirty": 30, "half an": 0.5, "half a": 0.5}
_CMD = (
    ("open", re.compile(r"^(?:please\s+)?(?:open|show|launch|bring up)(?: me)?(?: my| the)?\s+"
                        r"(timeline|insights|dashboard|stats|day map)\W*$", re.I)),
    ("pause", re.compile(r"^(?:please\s+)?(?:pause|stop (?:listening|recording|capturing|watching)|go private)"
                         r"(?:\s+(?:for\s+)?(\d+|an?|one|two|three|four|five|ten|fifteen|twenty|thirty|half an?)"
                         r"\s*(m|mins?|minutes?|h|hrs?|hours?))?\W*$", re.I)),
    ("resume", re.compile(r"^(?:please\s+)?(?:resume|unpause|start (?:listening|recording|capturing)(?: again)?)\W*$",
                          re.I)),
    ("unfocus", re.compile(r"^(?:clear|stop|end|drop|cancel)\s+(?:my\s+|the\s+)?focus\W*$", re.I)),
    ("focus", re.compile(r"^(?:(?:i (?:want|need) to|let me|let'?s|help me)\s+)?"
                         r"(?:focus on|set (?:my )?focus(?: to)?|my focus is)\s+(.{3,}?)\W*$", re.I)),
    ("hush", re.compile(r"^(?:stop|stop talking|shush|hush|quiet|be quiet|shut up|enough|never ?mind|cancel|"
                        r"that'?s all|close)\W*$", re.I)),
)

ANSWER_STYLE = """The user asked this out loud; the <context> items are shown beside your reply.
Answer in one or two short sentences, under 35 words, plain text: the answer first,
then when and where (day, time, app). No preamble, no restating the question, no
hedging. If the context doesn't answer it, say so in under ten words."""

SCREEN_STYLE = """The <context> is the window the user is looking at right now. In one or two
short sentences, under 40 words: what it is, then what matters for their question. For
a summary, give the gist of the content, not the interface. Use only this <context>:
never reuse an earlier answer. If the text is thin, name the app and window and say you
can't read its main content."""

CHAT_STYLE = """This is conversation, not a search. Reply in one short sentence, plain text,
easy to read aloud. If asked what you can do: recall what they saw or heard ("what was
that form on Friday?"), explain their screen ("what's on my screen?"), show where their
day went ("how was my day?"), and keep them on track ("focus on ...")."""


def command(text: str) -> tuple[str, object] | None:
    """(kind, argument) if this is something to do rather than a question (D31)."""
    t = text.strip()
    for kind, rx in _CMD:
        m = rx.match(t)
        if not m:
            continue
        if kind == "pause":
            n = m[1] and (float(m[1]) if m[1].isdigit() else _NUMS.get(m[1].lower(), 1))
            return kind, (n * (60 if m[2][0].lower() == "h" else 1) if n else None)
        return kind, (m[1].strip() if m.groups() else None)
    return None


def parse_wake(text: str) -> str | None:
    """The question after the wake word, "" if only the name was said, else None."""
    m = _WAKE.match(text.strip())
    return m.group(1).strip(" .,!?") if m else None


def route(text: str, last: dict | None = None, now: int | None = None) -> tuple[str, str]:
    """(mode, search query). `last` is the previous turn of this conversation, if
    recent: {"mode", "query", "ts"}. A short follow-up inherits its mode and topic."""
    from .plugin import time_window
    now = now or now_ms()
    t = text.strip()
    if command(t):
        return "command", t
    fresh_time = time_window(t, now) is not None
    if _STATS.search(t):
        return "stats", t
    # "And yesterday?" / "what about Discord?" after a usage answer: same question,
    # new time or new app. The turn keeps its term and time label for this (D31).
    if (last and last["mode"] == "stats" and now - last["ts"] < config.CONVO_S * 1000
            and len(t.split()) <= 8 and (_STATS_FOLLOW.match(t) or (fresh_time and not _PAST.search(t)))):
        q = t if insights.terms(t) else f"{t} {last.get('term', '')}"
        return "stats", (q if fresh_time else f"{q} {last.get('when', '')}").strip()
    if _CHAT.search(t) and not _PAST.search(t):
        return "chat", t
    if last and last["mode"] in ("recall", "screen") and _SHOW.search(t) and len(t.split()) <= 8:
        return "show", t                          # "show me the first one": zoom evidence
    past = bool(_PAST.search(t))
    if _SCREEN.search(t) and not past:
        return "screen", t
    # "What was on my screen?" / "that page I was on": now, or captured earlier?
    if _SCREEN_WORD.search(t) and past and not fresh_time:
        return "clarify", t
    if _BARE_THIS.match(t) and not (last and last["mode"] == "screen"):
        return "clarify", t
    # A short follow-up ("and when does it close?") continues the last topic.
    if (last and now - last["ts"] < config.CONVO_S * 1000 and last["mode"] in ("recall", "screen")
            and not fresh_time and len(t.split()) <= 12 and _FOLLOW.search(t)):
        return last["mode"], f"{last['query']} {t}"
    if past or fresh_time:
        return "recall", t
    if _DEICTIC.match(t):
        return "clarify", t                       # "what's this?": on screen now, or earlier?
    # A general question with no past or screen cue ("how does OAuth work?"): talk.
    if re.match(r"(?:what|who|how|why|when|where|is|are|can|could|does|do|should|will)\b", t, re.I):
        return "chat", t
    return "recall", t                  # a bare topic ("the McKinsey form") means: find it


def interpret(reply: str, now: int | None = None) -> str | None:
    """A reply to CLARIFY_Q -> "screen", "recall", or None if still unclear."""
    from .plugin import time_window
    earlier = bool(_PAST.search(reply) or time_window(reply, now or now_ms())
                   or re.search(r"\b(?:earlier|before|ago|previous|old|that day)\b", reply, re.I))
    if earlier:
        return "recall"
    if _NOW.search(reply) or _SCREEN_WORD.search(reply):
        return "screen"
    return None


def excerpt(text: str, terms: list[str], limit: int = 220) -> str:
    """The most relevant line or two, readable: long tokens (URLs, ids) folded."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    scored = sorted(lines, key=lambda ln: -sum(t in ln.lower() for t in terms))
    best = [ln for ln in scored[:2] if ln]
    out = " · ".join(" ".join(w if len(w) <= 32 else w[:28] + "…" for w in ln.split()) for ln in best)
    return out if len(out) <= limit else out[: limit - 1] + "…"


def _app(app: str | None) -> str:
    return insights.app_name(app) if app else ""


def _item(ref, ts, kind, text, frame, via, terms) -> dict:
    return {
        "ref": ref, "ts": ts, "kind": kind, "via": via,
        "day": time.strftime("%a %d %b", time.localtime(ts / 1000)),
        "time": time.strftime("%H:%M", time.localtime(ts / 1000)),
        "app": _app(frame["app"]) if frame else "",
        "title": (frame or {}).get("title") or "",
        "thumb": (frame or {}).get("thumb_path"),
        "excerpt": excerpt(text, terms), "text": text[:600],
    }


def gather_evidence(store: Store, question: str, now: int | None = None,
                    k: int = config.ASK_EVIDENCE) -> tuple[list[dict], str | None, list[str]]:
    """(evidence, time label, highlight terms). Best match first."""
    from .plugin import time_window
    now = now or now_ms()
    w = time_window(question, now)
    since, until = (w[0], w[1]) if w else (0, now)
    terms = [t.strip('"') for t in (fts_query(question) or "").split(" OR ") if t]
    junk = furniture(store)
    items: list[dict] = []
    if terms:
        for h in hybrid(store, question, since, until, k + 2):
            if h["ref"] < 0 and parse_wake(h["text"]) is not None:
                continue                  # an old "Jimmy, …" command is not evidence (D27)
            frame = store.frame_for(h["ref"], h["ts"])
            items.append(_item(h["ref"], h["ts"], "screen" if h["ref"] > 0 else "heard",
                               h["text"], frame, h["via"], terms))
        items = items[:k]
    if not items:
        # No topic ("what was I doing on Tuesday?"): what was on screen then.
        a_since = since if w else now - jcfg.DEFAULT_LOOKBACK_H * 3600_000
        for a in store.activity(a_since, until, k):
            frame = store.latest_frame(a["app"], a["title"], a_since, until)
            if frame and a["title"] not in junk and not is_own_window(a["app"], a["title"]):
                items.append(_item(-10_000_000 - frame["id"], frame["ts"], "activity",
                                   f"{a['title']} (seen {a['frames']} times)", frame, "activity", terms))
    return items, (w[2] if w else None), terms


def to_snippets(items: list[dict]) -> list[Snippet]:
    out = []
    for e in items:
        where = f"screen · {e['app']} — {e['title']}" if e["kind"] != "heard" else "heard near mic"
        out.append(Snippet(e["ts"], where, e["text"]))
    return out


def speakable(text: str, limit: int = config.VOICE_MAX_CHARS) -> str:
    """The first sentences that fit, for reading aloud."""
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())):
        if len(out) + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out or text[:limit]


class Voice:
    """Windows' built-in text-to-speech (SAPI via comtypes, already installed).
    Its own thread (COM likes one), interruptible, reports start and end."""

    def __init__(self, on_start: Callable[[], None] = lambda: None,
                 on_end: Callable[[], None] = lambda: None):
        self.on_start, self.on_end = on_start, on_end
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="voice").start()

    def say(self, text: str) -> None:
        if text.strip():
            self._stop.clear()
            self._q.put(text)

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self._stop.set()
        self._q.put(None)

    def _run(self) -> None:
        try:
            import comtypes
            from comtypes.client import CreateObject
            comtypes.CoInitialize()
            sapi = CreateObject("SAPI.SpVoice")
            sapi.Rate = config.VOICE_RATE
            sapi.Volume = config.VOICE_VOLUME
        except Exception as exc:
            print(f"[voice] unavailable: {type(exc).__name__}: {exc}")
            return
        while (text := self._q.get()) is not None:
            self.on_start()
            try:
                sapi.Speak(text, 1)                     # 1 = asynchronous
                while not sapi.WaitUntilDone(100):
                    if self._stop.is_set():
                        sapi.Speak("", 3)               # 3 = async + purge: stop now
                        break
            except Exception as exc:
                print(f"[voice] {type(exc).__name__}: {exc}")
            finally:
                self.on_end()


class Asker:
    """Turns a spoken or typed question into overlay events: answer_start,
    answer_evidence, answer_delta, answer_end (or answer_error)."""

    def __init__(self, store: Store, publish: Callable[[dict], None],
                 speak: Callable[[str], None] | None = None, jimmy=None,
                 screen_now: Callable[[], dict | None] | None = None,
                 actions: dict[str, Callable] | None = None):
        self.store, self.publish, self.speak = store, publish, speak
        self.screen_now = screen_now or (lambda: None)
        self.actions = actions or {}      # D31: pause, resume, focus, hush, state (from the bus)
        self._jimmy = jimmy
        self._lock = threading.Lock()
        self.listen_until = 0
        self._n = 0
        self.turns: list[dict] = []        # this conversation: {q, a, mode, query, ts}
        self.session = ""
        self.pending: dict | None = None   # D28: a question Jimmy asked back, awaiting a reply
        self.busy = 0
        self.last_evidence: list[dict] = []

    def hear(self, ts_end: int, source: str, text: str) -> bool:
        """Called for every transcribed segment. True if it was meant for Jimmy."""
        if source != "mic":
            return False
        if self.pending and now_ms() < self.listen_until and text.strip():
            # The reply to Jimmy's question: no wake word needed.
            self.listen_until = 0
            reply = parse_wake(text)
            body = reply if reply is not None else text.strip()
            if command(body) or (reply is not None and len(reply.split()) >= 4 and interpret(reply) is None):
                self.pending = None       # "stop", or "Jimmy, <a new question>": drop the old one
                self.ask(body, "voice")
                return True
            self.resolve(body, "voice")
            return True
        q = parse_wake(text)
        if q is None:
            if now_ms() < self.listen_until and (len(text.split()) >= 2 or command(text)):
                self.listen_until = 0
                self.ask(text.strip(), "voice")
                return True
            return False
        if len(q.split()) < 2 and not command(q):       # just "Jimmy": listen for the question
            self.listen_until = now_ms() + config.LISTEN_WINDOW_S * 1000
            self.publish({"type": "listening"})
            return True
        self.ask(q, "voice")
        return True

    def ask(self, question: str, source: str = "typed", force: tuple[str, str] | None = None) -> None:
        self.busy += 1
        threading.Thread(target=self._run, args=(question, source, force), daemon=True, name="ask").start()

    def resolve(self, reply: str, source: str = "voice") -> None:
        """Answer to "now, or earlier?" (D28). Unclear twice → assume earlier."""
        p = self.pending
        if not p:
            return
        mode = interpret(reply)
        if mode is None and p["asked"] < 2:      # _answer counts the re-ask
            self.ask(p["q"], source, force=("clarify", p["q"]))
            return
        self.pending = None
        mode = mode or "recall"
        query = f"{p['q']} {reply}" if mode == "recall" else p["q"]
        self.ask(f"{p['q']} ({reply})", source, force=(mode, query))

    def choose(self, choice: str) -> None:
        """The same, from the card's buttons."""
        self.resolve("right now on my screen" if choice == "now" else "something I saw earlier", "typed")

    def wait_idle(self, timeout: float = 90) -> bool:
        end = time.time() + timeout
        while self.busy and time.time() < end:
            time.sleep(0.2)
        return not self.busy

    def _jim(self):
        if self._jimmy is None:
            from jimmy.core import Jimmy
            self._jimmy = Jimmy.default()
        return self._jimmy

    def _conversation(self, now: int) -> dict | None:
        """The last turn if this question continues a conversation; else start anew."""
        if self.turns and now - self.turns[-1]["ts"] < config.CONVO_S * 1000:
            return self.turns[-1]
        self.turns, self.session = [], f"convo-{now}"
        return None

    def _screen_evidence(self) -> list[dict]:
        now = self.screen_now()
        if not now:
            return []
        raw = now["text"]
        kept = "\n".join(ln for ln in raw.split("\n") if ln.strip() not in furniture(self.store))
        # A page you keep coming back to repeats across windows just like a sidebar
        # does. If "furniture" is most of the window, it was the content (D30).
        text = kept if len(kept) >= len(raw) / 2 else raw
        item = _item(-20_000_000 - now["frame"]["id"], now["frame"]["ts"], "now",
                     text or now["frame"]["title"], now["frame"], "now", [])
        # The newest text, not the oldest: this is about the screen now.
        item.update(text=f"{now['frame']['title']}\n{text[-3900:]}", day="Now", time="")
        return [item]

    def _do(self, kind: str, arg) -> str:
        """Carry out a command the user gave (D31). Returns what to say about it."""
        act = self.actions
        if kind == "hush":
            self.pending, self.listen_until = None, 0
            act.get("hush", lambda: None)()
            self.publish({"type": "answer_close"})
            return "Okay."
        if kind == "open":
            view = "timeline" if arg.lower() == "timeline" else "insights"
            self.publish({"type": "open_view", "view": view})
            return f"Opening {view}."
        need = {"pause": "pause", "resume": "resume", "focus": "focus", "unfocus": "focus"}[kind]
        if need not in act:
            return "I can't do that from here."
        if kind == "pause":
            act["pause"](arg or 120)
            said = f"Paused for {insights.dur((arg or 120) * 60_000)}."
        elif kind == "resume":
            act["resume"]()
            said = "Listening again."
        else:
            act["focus"](arg if kind == "focus" else None)
            said = f"Focus set: {arg}." if kind == "focus" else "Focus cleared."
        if "state" in act:
            self.publish({"type": "state", **act["state"]()})
        return said

    def _stats(self, aid: str, question: str, query: str, source: str) -> None:
        """Where the time went, from captures, in one line and a chart (D31). No model."""
        from .plugin import time_window
        now = now_ms()
        line, data = insights.answer(self.store, query, time_window(query, now), now)
        self.last_evidence = []
        self.publish({"type": "answer_evidence", "id": aid, "mode": "stats", "evidence": [],
                      "window": data["label"], "terms": [], "days": [], "stats": data})
        self.publish({"type": "answer_delta", "id": aid, "text": line})
        self.publish({"type": "answer_end", "id": aid, "text": line})
        self.turns.append({"q": question, "a": line, "mode": "stats", "query": query, "ts": now,
                           "term": (data["match"] or {}).get("term", ""), "when": data["label"]})
        if source == "voice" and self.speak and config.VOICE_ANSWERS:
            self.speak(line)

    def _run(self, question: str, source: str, force: tuple[str, str] | None = None) -> None:
        try:
            self._answer(question, source, force)
        finally:
            self.busy -= 1

    def _answer(self, question: str, source: str, force: tuple[str, str] | None) -> None:
        with self._lock:                                # one answer at a time
            self._n += 1
            aid = f"{int(time.time())}-{self._n}"
            now = now_ms()
            last = self._conversation(now)
            mode, query = force or route(question, last, now)
            if mode == "command":
                kind, arg = command(question)
                said = self._do(kind, arg)
                self.publish({"type": "toast", "text": said, "icon": kind})
                if source == "voice" and self.speak and kind != "hush":
                    self.speak(said)
                return
            if mode == "show":
                # "Show me the best match": open evidence already on screen, no new search.
                words = question.lower().replace("?", "").split()
                idx = next((_ORDINAL[w] for w in words if w in _ORDINAL), 0)
                idx = len(self.last_evidence) - 1 if idx < 0 else idx
                if 0 <= idx < len(self.last_evidence):
                    self.publish({"type": "open_evidence", "index": idx})
                    said = "Here it is."
                else:
                    said = "There's no such match."
                    self.publish({"type": "toast", "text": said, "icon": "show"})
                if source == "voice" and self.speak:
                    self.speak(said)
                return
            # A new question drops a question Jimmy asked back; only a re-ask keeps its count.
            asked = (self.pending or {}).get("asked", 0) if force and force[0] == "clarify" else 0
            self.pending = None
            history = [{"q": t["q"], "a": t["a"]} for t in self.turns[-2:]]
            self.publish({"type": "answer_start", "id": aid, "question": question, "source": source,
                          "mode": mode, "history": history})
            if mode == "clarify":
                # D28: can't tell the screen now from a screen captured earlier: ask.
                self.pending = {"q": question, "asked": asked + 1, "ts": now}
                self.listen_until = now_ms() + config.CLARIFY_WAIT_S * 1000
                self.publish({"type": "answer_evidence", "id": aid, "mode": "clarify", "evidence": [],
                              "window": None, "terms": [], "days": []})
                self.publish({"type": "answer_delta", "id": aid, "text": CLARIFY_Q})
                self.publish({"type": "answer_end", "id": aid, "text": CLARIFY_Q, "awaiting": True})
                self.publish({"type": "listening", "prompt": "listening… now, or earlier?"})
                if source == "voice" and self.speak:
                    self.speak(CLARIFY_Q)
                return
            try:
                if mode == "stats":
                    return self._stats(aid, question, query, source)
                if mode == "chat":
                    items, label, terms = [], None, []
                elif mode == "screen":
                    items, label, terms = self._screen_evidence(), "now", []
                else:
                    items, label, terms = gather_evidence(self.store, query)
                self.last_evidence = items
                days = sorted({e["day"] for e in items})
                self.publish({"type": "answer_evidence", "id": aid, "mode": mode, "evidence": items,
                              "window": label, "terms": terms, "days": days})
                jim = self._jim()
                style = {"chat": CHAT_STYLE, "screen": SCREEN_STYLE}.get(mode, ANSWER_STYLE)
                if mode != "chat" and not items:
                    text = ("I can't see a window I'm allowed to read." if mode == "screen" else
                            "Nothing I captured matches that.")
                    self.publish({"type": "answer_delta", "id": aid, "text": text})
                elif not jim.llm.configured:
                    text = "Here's what I found; there's no model key to summarise it."
                    self.publish({"type": "answer_delta", "id": aid, "text": text})
                else:
                    text = ""
                    # The screen changes: a screen answer gets no history, and joins none,
                    # or the last screen's answer gets repeated for this one (D29).
                    session = f"screen-{aid}" if mode == "screen" else self.session
                    for piece in jim.ask_stream(question, session=session,
                                                snippets=to_snippets(items), instructions=style):
                        text += piece
                        self.publish({"type": "answer_delta", "id": aid, "text": piece})
                self.publish({"type": "answer_end", "id": aid, "text": text})
                self.turns.append({"q": question, "a": text, "mode": mode, "query": query, "ts": now_ms()})
                if source == "voice" and self.speak and config.VOICE_ANSWERS:
                    self.speak(speakable(text))
            except LLMError as exc:
                self.publish({"type": "answer_error", "id": aid, "error": str(exc)[:200]})
            except Exception as exc:                    # an answer failing must never stop capture
                self.publish({"type": "answer_error", "id": aid, "error": f"{type(exc).__name__}: {exc}"[:200]})
