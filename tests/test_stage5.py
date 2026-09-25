"""One runnable check for stage 5 (recall timeline). `python tests/test_stage5.py`.

The embedding model is replaced by a tiny deterministic one (hashed words), so
this runs without Ollama; it tests the plumbing, not bge-m3's quality.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.recall as recall  # noqa: E402
from ambient.api import OverlayAPI  # noqa: E402
from ambient.db import Store  # noqa: E402

MIN = 60_000
T0 = 1_800_000_000_000
SYN = {"consulting": "mckinsey", "firm": "mckinsey"}   # a pretend "meaning": synonyms share a slot


VOCAB: dict[str, int] = {}


def fake_embed(texts, model=None):
    """Bag of words with one slot per distinct word: no hash collisions, so the
    only "meaning" is the SYN table (a hashed version collided and failed)."""
    out = []
    for t in texts:
        v = np.zeros(512, dtype=np.float32)
        for w in t.lower().split():
            w = SYN.get(w.strip(".,?"), w.strip(".,?"))
            v[VOCAB.setdefault(w, len(VOCAB)) % 512] += 1.0
        out.append(v.tolist())
    return out


recall.embed = fake_embed


def store_with_history() -> Store:
    s = Store(":memory:")
    for i in range(4):   # a sidebar line in 4 windows = furniture
        w = s.open_window(ts=T0 + i)
        f = s.add_frame(w, "claude.exe", "Claude", ts=T0 + i * MIN, thumb_path=f"thumbs/x/{i}.jpg")
        s.add_text(f, "uia", f"Image suspicion check sidebar\nlunch notes number {i}")
    w = s.open_window(ts=T0 + 10 * MIN)
    f = s.add_frame(w, "chrome.exe", "McKinsey Forward Application", ts=T0 + 10 * MIN)
    s.add_text(f, "uia", "McKinsey Forward application form\nApplications close on Monday")
    s.add_audio(T0 + 12 * MIN, T0 + 12 * MIN + 5000, "mic", "the agent development kit from google")
    return s


def test_chunks_split_on_lines():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(30))
    parts = recall.chunks(text, size=800)
    assert all(len(p) <= 800 for p in parts) and len(parts) > 1
    assert "".join(parts).replace("\n", "") == text.replace("\n", ""), "nothing lost, nothing added"
    assert recall.chunks("  \n\n") == []
    print("ok  chunking")


def test_index_is_incremental_and_semantic_finds_meaning():
    s = store_with_history()
    first = recall.index(s, model="fake")
    assert first > 0 and recall.index(s, model="fake") == 0, "already indexed blocks aren't redone"
    s.add_audio(T0 + 20 * MIN, T0 + 20 * MIN + 1, "mic", "new speech later")
    assert recall.index(s, model="fake") == 1, "only the new block"
    hits = recall.semantic(s, "consulting firm", model="fake")
    assert hits and "McKinsey" in hits[0]["chunk"], "a synonym finds it by meaning"
    assert recall.semantic(Store(":memory:"), "anything", model="fake") == [], "empty index, no results"
    print("ok  incremental index, meaning search")


def test_hybrid_merges_strips_furniture_and_dedupes():
    s = store_with_history()
    recall.index(s)
    recall._furniture["at"] = 0                     # fresh furniture for this store
    hits = recall.hybrid(s, "mckinsey application", k=10)
    assert hits[0]["app"] == "chrome.exe" and "words" in hits[0]["via"] and "meaning" in hits[0]["via"]
    texts = [h["text"] for h in recall.hybrid(s, "image suspicion check lunch", k=10)]
    assert all("Image suspicion check sidebar" not in t for t in texts), "sidebar furniture is stripped"
    assert len(texts) == len(set(texts)), "no duplicate texts"
    print("ok  hybrid: merged, furniture stripped, deduped")


def test_hybrid_survives_without_embedding_model():
    def down(texts, model=None):
        raise recall.LLMError("unreachable")
    s = store_with_history()
    saved, recall.embed = recall.embed, down
    try:
        hits = recall.hybrid(s, "McKinsey application")
        assert hits and all(h["via"] == "words" for h in hits), "keywords still answer"
    finally:
        recall.embed = saved
    print("ok  keyword fallback when the model is down")


def test_timeline_api_and_thumb_traversal():
    import tempfile
    from ambient import config
    s = store_with_history()
    with tempfile.TemporaryDirectory() as d:
        saved = (config.DATA_DIR, config.THUMB_DIR)
        config.DATA_DIR, config.THUMB_DIR = Path(d), Path(d) / "thumbs"
        (Path(d) / "thumbs" / "x").mkdir(parents=True)
        (Path(d) / "thumbs" / "x" / "0.jpg").write_bytes(b"\xff\xd8jpeg")
        (Path(d) / "secret.txt").write_text("private")
        api = OverlayAPI({"state": lambda: {}, "pause": print, "resume": print, "dismiss": print,
                          **recall.timeline_hooks(s)}).start()
        get = lambda route: json.load(urllib.request.urlopen(urllib.request.Request(  # noqa: E731
            f"{api.url}/{route}", headers={"Authorization": f"Bearer {api.token}"}), timeout=5))
        try:
            day = __import__("time").strftime("%Y-%m-%d", __import__("time").localtime(T0 / 1000))
            tl = get(f"timeline?day={day}")
            assert tl["day"] == day and len(tl["frames"]) == 5 and day in tl["days"]
            fr = get(f"frame?id={tl['frames'][-1]['id']}")
            assert "McKinsey" in fr["text"][0]["text"] and fr["speech"], "frame text + nearby speech"
            assert get("thumb?path=thumbs/x/0.jpg")["data"].startswith("data:image/jpeg;base64,")
            for evil in ("thumb?path=secret.txt", "thumb?path=thumbs/../secret.txt"):
                try:
                    get(evil)
                except urllib.error.HTTPError as e:
                    assert e.code == 404
                else:
                    raise AssertionError(f"{evil} must not be served")
            assert get("search?q=mckinsey")["results"], "search route answers"
        finally:
            api.stop()
            config.DATA_DIR, config.THUMB_DIR = saved
    print("ok  timeline API; thumbs can't escape their folder")


def test_wake_word_and_text_helpers():
    from ambient.ask import excerpt, parse_wake, speakable
    assert parse_wake("Jimmy, what was that form on Friday?") == "what was that form on Friday"
    assert parse_wake("hey jimmie what did I read") == "what did I read"
    assert parse_wake("Jimmy.") == "" and parse_wake("okay Jimmy") == ""
    assert parse_wake("I told Jimmy about it") is None, "the name mid-sentence is not a command"
    long = "x" * 80
    ex = excerpt(f"nothing here\nthe McKinsey form {long} closes Monday", ["mckinsey"])
    assert ex.startswith("the McKinsey form") and long not in ex, "the relevant line, long tokens folded"
    assert speakable("One. Two is longer. Three!", limit=16) == "One.", "reads whole sentences only"
    print("ok  wake word, excerpt, speakable")


def test_asker_answers_voice_questions_and_speaks_only_those():
    from ambient.ask import Asker

    class FakeJimmy:
        class llm:
            configured = True
        def ask_stream(self, q, session, snippets, instructions):
            assert snippets, "the answer is built from the evidence shown"
            yield "The McKinsey form, "
            yield "Friday 14:09."

    import ambient.ask as ask_mod
    ask_mod.now_ms = lambda: T0 + 60 * MIN      # the fixture's "now"; T0 lies in the real future
    s = store_with_history()
    recall.index(s)
    events, spoken = [], []
    a = Asker(s, events.append, speak=spoken.append, jimmy=FakeJimmy())

    assert a.hear(0, "mic", "Jimmy.") is True and events[-1] == {"type": "listening"}
    assert a.hear(0, "mic", "what was the mckinsey application") is True, "the next line is the question"
    for _ in range(100):
        if any(e["type"] == "answer_end" for e in events):
            break
        __import__("time").sleep(0.05)
    kinds = [e["type"] for e in events]
    assert kinds[:3] == ["listening", "answer_start", "answer_evidence"] and kinds[-1] == "answer_end", kinds
    ev = next(e for e in events if e["type"] == "answer_evidence")
    assert ev["evidence"][0]["app"] == "Chrome" and "McKinsey" in ev["evidence"][0]["title"]
    assert next(e for e in events if e["type"] == "answer_end")["text"] == "The McKinsey form, Friday 14:09."
    assert spoken == ["The McKinsey form, Friday 14:09."], "spoken questions are answered aloud"

    events.clear()
    a._run("mckinsey application", "typed")
    assert len(spoken) == 1, "typed questions are answered silently"
    assert a.hear(0, "loopback", "Jimmy, what was that") is False, "only the user's mic can ask"
    assert a.hear(0, "mic", "just talking about lunch") is False
    print("ok  asker: voice in, evidence + answer out, spoken reply")


def test_router_and_follow_ups():
    """D27: not every question is a search of the past."""
    from ambient.ask import route
    for text, mode in (("can you listen to me", "chat"), ("thanks Jimmy", "chat"),
                       ("what can you do", "chat"), ("how does OAuth work", "chat"),
                       ("what's on my screen", "screen"), ("summarise this page", "screen"),
                       ("what am I looking at right now", "screen"),
                       ("what was that consulting application on Friday", "recall"),
                       ("what did I do yesterday", "recall"), ("the McKinsey form", "recall")):
        assert route(text, now=T0)[0] == mode, f"{text!r} -> {route(text, now=T0)[0]}, wanted {mode}"
    last = {"mode": "recall", "query": "consulting application Friday", "ts": T0 - 30_000}
    assert route("and when does it close?", last, T0) == ("recall", "consulting application Friday and when does it close?")
    stale = dict(last, ts=T0 - 3600_000)
    assert route("and when does it close?", stale, T0)[1] == "and when does it close?", "an hour later is a new topic"
    print("ok  router: chat / screen / recall, follow-ups")


def test_commands_are_never_evidence():
    import ambient.ask as ask_mod
    s = store_with_history()
    s.add_audio(T0 + 13 * MIN, T0 + 13 * MIN + 1, "command", "Jimmy what was the mckinsey application")
    s.add_audio(T0 + 14 * MIN, T0 + 14 * MIN + 1, "mic", "Jimmy can you find the mckinsey application")  # pre-D27
    recall.index(s)
    assert s.search('"mckinsey"', 20) and all(h["source"] != "command" for h in s.search('"mckinsey"', 20))
    ask_mod.now_ms = lambda: T0 + 60 * MIN
    items, _, _ = ask_mod.gather_evidence(s, "the mckinsey application", now=T0 + 60 * MIN)
    assert items and all("jimmy" not in e["text"].lower() for e in items), [e["text"] for e in items]
    print("ok  commands to Jimmy are never evidence")


def test_jimmy_never_captures_itself():
    from ambient.redact import Exclusions, is_own_window
    assert is_own_window("C:/x/electron.exe", "Jimmy · Timeline") and is_own_window("electron.exe", "Jimmy")
    assert not is_own_window("Code.exe", "Jimmy - Visual Studio Code")
    assert not is_own_window("electron.exe", "Slack")
    assert Exclusions().check(app="electron.exe", title="Jimmy") == "excluded-self: Jimmy's own window"
    s = store_with_history()
    w = s.open_window(ts=T0 + 30 * MIN)
    f = s.add_frame(w, "electron.exe", "Jimmy", ts=T0 + 30 * MIN)
    s.add_text(f, "uia", "McKinsey Forward application form shown again inside Jimmy")
    recall._furniture["at"] = 0
    assert all(h["app"] != "electron.exe" for h in recall.hybrid(s, "mckinsey application", k=10)), \
        "old self-captures are skipped when reading"
    print("ok  Jimmy never captures or cites itself")


def test_clarify_now_or_earlier():
    """D28: "what's this?" could mean the screen now or one captured earlier: ask."""
    from ambient.ask import interpret, route
    for text, mode in (("what is this", "clarify"), ("what was on my screen", "clarify"),
                       ("that page I was reading", "clarify"),
                       ("what was on my screen at 3pm yesterday", "recall"),
                       ("what is this page", "screen"), ("what's on my screen", "screen")):
        assert route(text, now=T0)[0] == mode, f"{text!r} -> {route(text, now=T0)[0]}, wanted {mode}"
    for reply, mode in (("right now", "screen"), ("the one on my screen", "screen"),
                        ("the one from Friday", "recall"), ("earlier", "recall"), ("umm not sure", None)):
        assert interpret(reply) == mode, f"{reply!r} -> {interpret(reply)}, wanted {mode}"
    last = {"mode": "recall", "query": "mckinsey", "ts": T0 - 30_000}
    assert route("what's this?", last, T0)[0] == "clarify", "a bare 'this' may mean the screen"
    assert route("what's this?", dict(last, mode="screen"), T0)[0] == "screen"
    assert route("show me the best match", last, T0)[0] == "show"
    assert route("open the second one", last, T0)[0] == "show"
    print("ok  router: clarify, replies, show")


def test_asker_asks_back_and_waits():
    import ambient.ask as ask_mod
    from ambient.ask import CLARIFY_Q, Asker

    class FakeJimmy:
        class llm:
            configured = True
        sessions = []
        def ask_stream(self, q, session, snippets, instructions):
            self.sessions.append(session)
            yield "It's the page you're on."

    clock = [T0 + 60 * MIN]
    ask_mod.now_ms = lambda: clock[0]
    s = store_with_history()
    shot = {"frame": {"id": 1, "ts": clock[0], "app": "chrome.exe", "title": "Docs", "thumb_path": None},
            "text": "Quarterly plan draft"}
    events, spoken = [], []
    a = Asker(s, events.append, speak=spoken.append, jimmy=FakeJimmy(), screen_now=lambda: shot)

    def turn(fn):
        events.clear()
        fn()
        assert a.wait_idle(10)
        return events

    ev = turn(lambda: a.hear(0, "mic", "Jimmy, what's this?"))
    end = next(e for e in ev if e["type"] == "answer_end")
    assert end["awaiting"] and end["text"] == CLARIFY_Q and spoken[-1] == CLARIFY_Q
    assert ev[-1]["type"] == "listening" and a.pending, "the pill keeps listening for the reply"

    ev = turn(lambda: a.hear(0, "mic", "umm"))           # unclear: asked once more, no wake word needed
    assert next(e for e in ev if e["type"] == "answer_end")["awaiting"] and a.pending["asked"] == 2
    ev = turn(lambda: a.hear(0, "mic", "the one on my screen right now"))
    assert a.pending is None
    assert next(e for e in ev if e["type"] == "answer_evidence")["mode"] == "screen"
    assert next(e for e in ev if e["type"] == "answer_end")["text"] == "It's the page you're on."
    assert a._jimmy.sessions[-1] != a.session, "a screen answer never sees (or feeds) the history"

    clock[0] += 3600_000                                 # a new conversation, not a follow-up
    turn(lambda: a.hear(0, "mic", "Jimmy, what is this"))
    ev = turn(lambda: a.choose("earlier"))              # the card's button does the same
    assert next(e for e in ev if e["type"] == "answer_evidence")["mode"] == "recall"

    turn(lambda: a.hear(0, "mic", "Jimmy, what's this"))
    clock[0] += 60_000                                   # no reply in time: a stray line is not an answer
    assert a.hear(0, "mic", "just talking about lunch") is False

    a.last_evidence = [{"id": 1}, {"id": 2}]
    a.turns[-1:] = [{"q": "x", "a": "y", "mode": "recall", "query": "mckinsey", "ts": clock[0]}]
    ev = turn(lambda: a.hear(0, "mic", "Jimmy, open the second one"))
    assert ev == [{"type": "open_evidence", "index": 1}] and spoken[-1] == "Here it is."
    print("ok  asker: asks back, waits, resolves by voice or button, shows evidence")


def test_demo_script_parses():
    from ambient.demo import DEFAULT_SCRIPT, parse
    steps = parse(DEFAULT_SCRIPT)
    assert all(c in {"wait", "card", "say", "reply", "show", "close"} for c, _ in steps), steps
    assert ("reply", "the one on my screen right now") in steps and ("close", "") in steps
    print("ok  demo script parses")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
