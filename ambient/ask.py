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

from . import config
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
_ORDINAL = {"first": 0, "best": 0, "top": 0, "second": 1, "third": 2}
CLARIFY_Q = ("Do you mean what's on your screen right now, or something you saw earlier?")

ANSWER_STYLE = """The user just asked this question out loud. The <context> items are the
evidence shown next to your answer on their screen. Reply in at most three short
sentences, plain text, easy to read aloud:
1. the direct answer;
2. when and where it was (day and time, app or page);
3. why you're confident, in a few words (what on screen or heard shows it).
If the context doesn't answer the question, say so in one sentence."""

SCREEN_STYLE = """The user is asking about what is on their screen right now. The <context> is
the text of the window they're looking at, with its app and title. Answer in at most
three short sentences, plain text, easy to read aloud: what it is, then what matters
for their question. If they ask for a summary, summarise the content, not the interface.
Use only this <context>: the screen changes, so never reuse an earlier answer. If the
text is thin (menus, a sidebar, a title), say which app and window it is and that you
can't read its main content."""

CHAT_STYLE = """The user is talking to you out loud; this is conversation, not a search of
their history. Reply naturally and briefly (one or two sentences, plain text, easy to
read aloud). What you can do, if they ask: recall anything they saw or heard on this
computer ("Jimmy, what was that form on Friday?"), explain what's on their screen now
("Jimmy, what's on my screen?"), and nudge them when they drift from what they meant
to do. You hear them through the microphone right now."""


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
    if _CHAT.search(t) and not _PAST.search(t):
        return "chat", t
    if last and last["mode"] in ("recall", "screen") and _SHOW.search(t) and len(t.split()) <= 8:
        return "show", t                          # "show me the first one": zoom evidence
    fresh_time = time_window(t, now) is not None
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
    return (app or "").removesuffix(".exe").replace("ms-teams", "Teams").capitalize() if app else ""


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
                 screen_now: Callable[[], dict | None] | None = None):
        self.store, self.publish, self.speak = store, publish, speak
        self.screen_now = screen_now or (lambda: None)
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
            if reply is not None and len(reply.split()) >= 4 and interpret(reply) is None:
                self.pending = None       # "Jimmy, <a new question>": drop the old one
                self.ask(reply, "voice")
                return True
            self.resolve(reply if reply is not None else text.strip(), "voice")
            return True
        q = parse_wake(text)
        if q is None:
            if now_ms() < self.listen_until and len(text.split()) >= 2:
                self.listen_until = 0
                self.ask(text.strip(), "voice")
                return True
            return False
        if len(q.split()) < 2:                          # just "Jimmy": listen for the question
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
        text = "\n".join(ln for ln in now["text"].split("\n") if ln.strip() not in furniture(self.store))
        item = _item(-20_000_000 - now["frame"]["id"], now["frame"]["ts"], "now",
                     text or now["frame"]["title"], now["frame"], "now", [])
        item.update(text=f"{now['frame']['title']}\n{text}"[:4000], day="Now", time="")
        return [item]

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
            if mode == "show":
                # "Show me the best match": open evidence already on screen, no new search.
                words = question.lower().split()
                idx = next((_ORDINAL[w] for w in words if w in _ORDINAL), 0)
                if idx < len(self.last_evidence):
                    self.publish({"type": "open_evidence", "index": idx})
                    if source == "voice" and self.speak:
                        self.speak("Here it is.")
                return
            history = [{"q": t["q"], "a": t["a"]} for t in self.turns[-2:]]
            self.publish({"type": "answer_start", "id": aid, "question": question, "source": source,
                          "mode": mode, "history": history})
            if mode == "clarify":
                # D28: can't tell the screen now from a screen captured earlier: ask.
                self.pending = {"q": question, "asked": (self.pending or {}).get("asked", 0) + 1, "ts": now}
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
                    text = ("I can't see a window to describe right now." if mode == "screen" else
                            "I couldn't find anything in what I captured that matches that.")
                    self.publish({"type": "answer_delta", "id": aid, "text": text})
                elif not jim.llm.configured:
                    text = "Here's what I found. I can't summarise it without the language model's key."
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
