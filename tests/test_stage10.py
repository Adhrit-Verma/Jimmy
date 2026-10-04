"""One runnable check for D41: understanding requests in context, reminders /
goals / memories by voice and in the Memory tab, feedback for asking without the
name, the virtual cursor, opening apps, and seeing the screen.
`python tests/test_stage10.py`. No network (the model is faked), no webcam."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient import act  # noqa: E402
from ambient.db import Store  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

NOW = int(datetime(2026, 10, 2, 23, 40).timestamp() * 1000)


class FakeLLM:
    """Answers the tool pick with the next scripted JSON, and records what it saw."""
    configured = True

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def chat(self, msgs, **kw):
        self.seen.append(msgs)
        return self.replies.pop(0) if self.replies else '{"tool": "answer", "args": {}}'


class FakeJimmy:
    def __init__(self, *replies):
        self.llm = FakeLLM(*replies)

    def ask_stream(self, q, session, snippets, instructions, **kw):
        yield "An answer."


def wired(mem: Memory, *replies, **extra):
    """An Asker with the same memory actions the bus gives it."""
    events, spoken = [], []
    ask_mod.now_ms = lambda: NOW
    acts = {"state": lambda: {}, "remind": lambda w, d, a: mem.add_reminder(w, d, a), "reminders": mem.reminders,
            "unremind": lambda: mem.set_reminder_state(None, "cancelled"),
            "cancel_reminder": lambda rid: mem.set_reminder_state(rid, "cancelled"),
            "update_reminder": mem.update_reminder, "goals": lambda: mem.goals("active"), "add_goal": mem.add_goal,
            "update_goal": mem.update_goal, "memories": mem.memories, "remember": mem.remember,
            "update_memory": mem.update_memory, "forget_memory": mem.forget, **extra}
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=FakeJimmy(*replies), actions=acts)

    def say(text):
        events.clear()
        a.hear(NOW, "mic", text, NOW - 2000)
        assert a.wait_idle(10), text
        return list(events)
    return a, say, spoken, events


def test_reminders_goals_memories_by_voice():
    mem = Memory(":memory:")
    rid = mem.add_reminder("check the railway booking", NOW + 3600_000)
    mem.add_reminder("call mom", NOW + 7200_000)
    a, say, spoken, _ = wired(mem, json.dumps({"tool": "reminder_update", "args": {"id": rid, "when": "10 am tomorrow"}}))
    say("Jimmy, change the railway reminder to 10 am tomorrow")
    seen = a._jimmy.llm.seen[0][1]["content"]
    assert f'#{rid} "check the railway booking"' in seen, "the model sees the reminders, with ids"
    r = next(x for x in mem.reminders() if x["id"] == rid)
    assert datetime.fromtimestamp(r["due_ts"] / 1000).strftime("%a %H:%M") == "Sat 10:00", r
    assert spoken[-1].startswith("Changed: check the railway booking"), spoken

    a, say, spoken, _ = wired(mem, '{"tool": "reminder_delete", "args": {"id": 999}}')
    say("Jimmy, delete that reminder")
    assert spoken[-1] == "Which reminder? I couldn't tell." and len(mem.reminders()) == 2, "an id not in the list: no guess"
    a, say, spoken, _ = wired(mem, '{"tool": "reminder_delete", "args": {"all": true}}')
    say("Jimmy, get rid of every reminder")
    assert "Say yes" in spoken[-1] and len(mem.reminders()) == 2, "all of them waits for a yes"
    say("yes")
    assert not mem.reminders(), "...and a yes does it"

    gid = mem.add_goal("finish the essay")
    a, say, spoken, _ = wired(mem, '{"tool": "goal_add", "args": {"text": "learn AWS"}}',
                              json.dumps({"tool": "goal_done", "args": {"id": gid}}), '{"tool": "list_goals", "args": {}}')
    say("Jimmy, add a goal to learn AWS")
    say("Jimmy, I finished the essay")
    say("Jimmy, what are my goals")
    assert spoken[-1] == "1 goal: learn AWS." and mem.goals("done")[0]["text"] == "finish the essay", spoken

    mid = mem.remember("I take the 8:15 train")
    a, say, spoken, _ = wired(mem, json.dumps({"tool": "memory_update", "args": {"id": mid, "text": "I take the 9:15 train"}}),
                              '{"tool": "list_memories", "args": {}}', json.dumps({"tool": "memory_delete", "args": {"id": mid}}))
    say("Jimmy, I take the 9:15 now, not the 8:15")
    assert mem.recall("train")[0]["text"] == "I take the 9:15 train", "edited, and the search index follows"
    say("Jimmy, what do you remember about me")
    assert spoken[-1] == "I remember: I take the 9:15 train.", spoken
    say("Jimmy, forget about the train")
    assert not mem.memories() and not mem.recall("train")
    mem.set_intent("ship the timeline")
    assert any(g["text"] == "ship the timeline" for g in mem.goals()), "a focus is a goal too"
    print("ok  by voice: reminders moved/deleted by id from <state>, goals done, memories edited and forgotten")


def test_reminder_without_a_what_asks():
    mem = Memory(":memory:")
    a, say, spoken, events = wired(mem)
    say("Jimmy, set a reminder for tomorrow")
    assert spoken[-1] == "What should I remind you about?" and not mem.reminders()
    say("to call mom")                                    # no name: it's the answer
    r = mem.reminders()
    assert r and r[0]["text"] == "call mom" and datetime.fromtimestamp(r[0]["due_ts"] / 1000).strftime("%a %H:%M") == "Sat 09:00"
    say("Jimmy, set a reminder for 5 to stretch")
    st = next(r for r in mem.reminders() if r["text"] == "stretch")
    assert datetime.fromtimestamp(st["due_ts"] / 1000).strftime("%H:%M") == "17:00", "for 5 is a time"
    print("ok  'set a reminder for tomorrow' asks what, and takes the answer without the name")


def test_feedback_without_the_name():
    mem = Memory(":memory:")
    looking = {"eye_contact": lambda a, b: True}
    a, say, _, events = wired(mem, **looking)
    say("what is on my screen")
    assert {"type": "heard", "text": "what is on my screen", "via": "eye contact"} in events, events
    a.followup_until = 0                                  # past the follow-up window
    events_skip = say("I am going to make tea now")
    assert any(e.get("type") == "heard" and e.get("skip") == "didn't sound like a request" for e in events_skip)
    a, say, _, events = wired(mem)                        # not looking: nothing shown for room talk
    assert not [e for e in say("I am going to make tea now") if e.get("type") == "heard"]

    from ambient.bus import ContextBus
    published = []
    b = ContextBus.__new__(ContextBus)
    b._api, b._asker, b._speaking, b._presence = type("A", (), {"publish": lambda s, e: published.append(e)})(), a, False, \
        {"contact": True}
    b._gate_memory, b._focus_memory = None, None
    b._on_speech_start("mic")
    assert published == [{"type": "hearing"}], "you start speaking while looking: 'listening…' at once"
    b._presence = {"contact": False}
    b._on_speech_start("mic")
    assert len(published) == 1, "not looking, no conversation: nothing"
    print("ok  feedback: 'listening…' as you start, then what it heard, or why it didn't take it")


def test_virtual_cursor_and_apps():
    T = act.Target
    ts = [T("Sign in", "ButtonControl", (100, 100, 200, 140), frozenset({"invoke"})),
          T("Sign up for free", "HyperlinkControl", (100, 200, 260, 220), frozenset({"invoke"})),
          T("Search", "EditControl", (300, 20, 700, 50), frozenset({"value"})),
          T("Password", "EditControl", (300, 80, 700, 110), frozenset({"value"}), password=True),
          T("Remember me", "CheckBoxControl", (100, 160, 120, 180), frozenset({"toggle"}))]
    assert act.best(ts, "the sign in button").name == "Sign in"
    assert act.best(ts, "sign up").name == "Sign up for free"
    assert act.best(ts, "remember me checkbox").name == "Remember me"
    assert act.best(ts, "search box", typing=True).name == "Search"
    assert act.best(ts, "the search", typing=False) is None, "a text box isn't something to press"
    assert act.best(ts, "delete my account") is None, "nothing like it: no guess"
    assert act.RISKY.search("Send message") and not act.RISKY.search("Sign in")
    links = [Path(p) for p in ("C:/SM/Google Chrome.lnk", "C:/SM/Uninstall Chrome.lnk", "C:/SM/Discord.lnk",
                               "C:/SM/Visual Studio Code.lnk", "C:/SM/Spotify Help.lnk")]
    assert act.find_app("chrome", links).stem == "Google Chrome" and act.find_app("discord", links).stem == "Discord"
    assert act.find_app("vs code", links).stem == "Visual Studio Code" and act.find_app("spotify", links) is None

    mem, did = Memory(":memory:"), []
    pointed = lambda target, text: did.append(("point", target, text)) or (a.make_offer("act", {"t": target}, bare=True)
                                                                           or f"Press \u201c{target}\u201d? Say yes.")
    a, say, spoken, events = wired(mem, point=pointed, perform=lambda d: did.append(("do", d)) or "Done.")
    say("Jimmy, click the sign in button")
    assert did == [("point", "sign in button", None)] and spoken[-1].endswith("Say yes.")
    say("yes")
    assert did[-1] == ("do", {"t": "sign in button"}) and spoken[-1] == "Done.", "only after the yes"
    say("Jimmy, type hello world into the search box")
    assert did[-1] == ("point", "search box", "hello world")
    say("no")
    assert {"type": "cursor", "hide": True} in events, "a no takes the cursor away"
    print("ok  virtual cursor: the right control by name, nothing pressed before a yes; apps by their shortcuts")


def test_memory_tab_api():
    from ambient.bus import ContextBus, memory_lists
    mem, published = Memory(":memory:"), []
    b = ContextBus.__new__(ContextBus)
    b._api = type("A", (), {"publish": lambda s, e: published.append(e)})()
    b._edit_memory(mem, {"op": "add", "kind": "reminder", "text": "pay rent", "when": "tomorrow at 10"})
    b._edit_memory(mem, {"op": "add", "kind": "goal", "text": "run 5k"})
    b._edit_memory(mem, {"op": "add", "kind": "memory", "text": "my bike is blue"})
    m = memory_lists(mem)
    assert [r["text"] for r in m["reminders"]] == ["pay rent"] and m["goals"][0]["text"] == "run 5k"
    b._edit_memory(mem, {"op": "update", "kind": "reminder", "id": m["reminders"][0]["id"], "text": "pay the rent"})
    b._edit_memory(mem, {"op": "done", "kind": "goal", "id": m["goals"][0]["id"]})
    b._edit_memory(mem, {"op": "update", "kind": "memory", "id": m["memories"][0]["id"], "text": "my bike is red"})
    m = memory_lists(mem)
    assert m["reminders"][0]["text"] == "pay the rent" and m["goals"][0]["state"] == "done"
    assert m["memories"][0]["text"] == "my bike is red"
    for kind, key in (("reminder", "reminders"), ("memory", "memories")):
        b._edit_memory(mem, {"op": "delete", "kind": kind, "id": m[key][0]["id"]})
    m = memory_lists(mem)
    assert not m["reminders"] and not m["memories"] and published.count({"type": "memory_changed"}) == 8
    print("ok  Memory tab: add, edit, done, delete for reminders, goals and memories; open windows refresh")


def test_seeing_the_screen():
    from jimmy import config as jcfg
    from jimmy.core import Jimmy, Snippet
    from jimmy.llm import LLM
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        has_image = isinstance(body["messages"][-1]["content"], list)
        calls.append((body["model"], has_image))
        if body["model"] == "vision/one":
            return httpx.Response(503, json={"error": "Worker local total request limit reached"})
        chunk = {"choices": [{"delta": {"content": f"seen by {body['model'].split('/')[1][:10]}"}}]}
        return httpx.Response(200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
                              headers={"content-type": "text/event-stream"})

    j = Jimmy(Memory(":memory:"), LLM(key="k", transport=httpx.MockTransport(handler)))
    real_vision = jcfg.VISION_MODELS
    jcfg.VISION_MODELS = ("vision/one", "vision/two")       # the chain, whichever provider is set (D44)
    try:
        out = "".join(j.ask_stream("what's this chart?", session="s", snippets=[Snippet(1, "screen", "Sales by month")],
                                   image="data:image/jpeg;base64,AAAA"))
    finally:
        jcfg.VISION_MODELS = real_vision
    assert calls[:2] == [("vision/one", True), ("vision/two", True)], calls
    assert out.startswith("seen by"), "the first vision model was busy: the second answered, with the picture"
    assert len(calls) == 2, "one attempt each, no retries, when another model can answer"

    with tempfile.TemporaryDirectory() as d:
        real = ask_mod.config.DATA_DIR
        try:
            ask_mod.config.DATA_DIR = Path(d)
            (Path(d) / "t.jpg").write_bytes(b"\xff\xd8jpeg")
            assert ask_mod.screen_image({"thumb": "t.jpg"}).startswith("data:image/jpeg;base64,")
            assert ask_mod.screen_image({"thumb": "missing.jpg"}) is None and ask_mod.screen_image({}) is None
        finally:
            ask_mod.config.DATA_DIR = real
    print("ok  seeing: the screen's picture goes to a vision model, falling back model by model, then text")


def test_understanding_routes():
    """The second live session's misses, routed by rules before any model."""
    q = lambda t: ask_mod.route(ask_mod.parse_wake("Jimmy " + t), now=NOW)  # noqa: E731
    assert q("show me the reminders")[0] == "command" and ask_mod.command("show me the reminders") == ("reminders", None)
    assert q("Can you see my eyes?")[0] == "presence"
    assert ask_mod.command("Navigate to Timeline") == ("open", "Timeline")
    assert ask_mod.command("Dewey Calibration") == ("calibrate", None)
    mem = Memory(":memory:")
    a, say, spoken, _ = wired(mem, '{"tool": "open_app", "args": {"name": "Chrome"}}', open_app=lambda n: f"Opening {n}.")
    say("Jimmy, give me open Chrome")
    assert spoken[-1] == "Opening Chrome.", "a muddled line reaches the model, which picks the tool"
    print("ok  understanding: the session's misses route by rule; the rest go to the model with context")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
