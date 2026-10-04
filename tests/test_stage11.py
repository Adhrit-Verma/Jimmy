"""One runnable check for D42: Jimmy as an agent. `python tests/test_stage11.py`.
No network (the model is scripted), no webcam; UI Automation is faked."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.ask as ask_mod  # noqa: E402
from ambient import act  # noqa: E402
from ambient.agent import Agent, render_screen  # noqa: E402
from ambient.db import Store  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

NOW = int(datetime(2026, 10, 3, 2, 0).timestamp() * 1000)
T = act.Target
SCREEN = [T("Search", "EditControl", (100, 100, 400, 130), frozenset({"value"}), hwnd=1),
          T("Search", "ButtonControl", (410, 100, 480, 130), frozenset({"invoke"}), hwnd=1),
          T("Delete account", "ButtonControl", (100, 300, 220, 330), frozenset({"invoke"}), hwnd=1),
          T("Close window", "ButtonControl", (900, 0, 940, 30), frozenset({"invoke"}), hwnd=1)]


def call(name: str, **args) -> dict:
    return {"tool_calls": [{"id": f"c{name}", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}], "content": ""}


class Script:
    """A model that answers each step from a list, and keeps what it was shown."""
    configured = True

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def chat_tools(self, messages, tools, **kw):
        self.seen.append([dict(m) for m in messages])
        return self.steps.pop(0) if self.steps else {"content": "Done.", "tool_calls": []}


def env(did: list, screen=SCREEN):
    return {"window": lambda: ("Test app", "Test window", (0, 0, 1000, 600)), "controls": lambda: list(screen),
            "status": lambda: "Jimmy, live.", "wiki_index": lambda: "- [Goals](me/goals.md)", "wiki": lambda p: "",
            "lists": lambda: "", "conversation": lambda: "", "look": lambda q, t: "The blue one is [2].",
            "search": lambda q: "", "open_app": lambda n: f"Opening {n}.", "close_app": lambda n: f"Closed {n}.",
            "open_url": lambda u: f"Opened {u}.", "cursor": lambda t, a: did.append(("cursor", a, t.name)),
            "perform": lambda t, text: did.append(("perform", t.name, text)) or "ok",
            "submit": lambda t: did.append(("submit", t.name)) or "ok", "progress": lambda s: None}


def test_plan_once_then_steps():
    did = []
    # reading order: [1] Close window (top right), [2] the Search box, [3] the Search button, [4] Delete
    llm = Script(call("plan", steps=["type carryminati", "press Search"]), call("type_text", id=2, text="carryminati"),
                 call("click", id=3), call("done", summary="Searched."))
    ag = Agent(llm, env(did))
    ag_time = __import__("ambient.agent", fromlist=["x"])
    ag_time.time.sleep = lambda s: None                     # no waiting for windows in a test
    out = ag.start("search for carryminati")
    assert out.kind == "await" and out.say.startswith("Here's the plan: 1. type carryminati.") and not did
    out = ag.answer(True)
    assert out.kind == "done" and out.say == "Searched."
    assert [d for d in did if d[0] == "perform"] == [("perform", "Search", "carryminati"), ("perform", "Search", None)]
    first = llm.seen[0][1]["content"]
    assert '[2] edit "Search"' in first and "<status>" in first and "<you>" in first, "the screen, numbered, in context"
    print("ok  a plan: one yes, then each step, shown with the cursor, then done")


def test_single_actions_ask_each_time_and_risky_always():
    did = []
    ag = Agent(Script(call("click", id=3), call("done", summary="Pressed.")), env(did))
    out = ag.start("press search")
    assert out.kind == "await" and out.say == "Press “Search”? Say yes." and ("cursor", "click", "Search") in did
    assert not [d for d in did if d[0] == "perform"], "nothing pressed before the yes"
    assert ag.answer(True).say == "Pressed."
    did.clear()
    ag = Agent(Script(call("plan", steps=["delete the account"]), call("click", id=4)), env(did))
    ag.start("delete my account")
    out = ag.answer(True)                                    # the plan is approved...
    assert out.kind == "await" and "Careful" in out.say, "...but 'Delete account' still asks on its own"
    assert ag.answer(False).say == "Okay, I won't." and not [d for d in did if d[0] == "perform"]
    print("ok  without a plan each action asks; anything risky asks even inside an approved plan")


def test_types_only_your_words_and_bad_ids():
    did = []
    llm = Script(call("type_text", id=2, text="best pizza near me"), call("ask_user", question="What should I type?"),
                 call("type_text", id=2, text="carry minati"), call("done", summary="Typed."))
    ag = Agent(llm, env(did))
    out = ag.start("type in the search bar")
    assert out.kind == "await" and out.data.get("ask"), "made-up text refused; it asks instead"
    assert "didn't say" in llm.seen[1][-1]["content"]
    out = ag.answer(None, "carry minati")                   # the user's answer...
    assert out.kind == "await" and "carry minati" in out.say, "...is allowed to be typed (after a yes)"
    ag2 = Agent(Script(call("click", id=99), call("ask_user", question="Which one?")), env([]))
    assert ag2.start("click the thing").data.get("ask"), "a number not on screen is refused, never guessed"
    print("ok  typing only words you said; a control number not on screen is refused")


def test_answers_and_jimmy_features_hand_back():
    ag = Agent(Script(call("answer", kind="history", question="what was the form on friday")), env([]))
    out = ag.start("what was that form on friday")
    assert out.kind == "answer" and out.data == {"kind": "history", "question": "what was the form on friday"}
    out = Agent(Script(call("list_reminders")), env([])).start("show me the reminders")
    assert out.data == {"tool": "jimmy", "action": "list_reminders", "args": {}}
    did = []
    ag = Agent(Script(call("look_at_screen", question="which is blue?"), call("click", id=3)), env(did))
    out = ag.start("click the blue button")
    assert out.kind == "await" and ag.task.messages[-2] == {"role": "tool", "tool_call_id": "clook_at_screen",
                                                             "content": "The blue one is [2]."}
    assert ("cursor", "click", "Search") in did, "looked, then pointed at what the picture showed"
    print("ok  questions and Jimmy's own features hand back; a look feeds the next step")


def test_screen_text_names_and_order():
    s = render_screen("Chrome", "Results", [T("Close (tab News)", "ButtonControl", (10, 0, 30, 20), frozenset({"invoke"})),
                                            T("First result", "HyperlinkControl", (100, 200, 400, 220),
                                              frozenset({"invoke"}))], (0, 0, 1000, 1000))
    assert '[1] button "Close (tab News)" @2,1' in s and '[2] link "First result" @25,21' in s
    print("ok  the screen for the model: numbered, typed, placed")


class FakeJimmy:
    def __init__(self, *steps):
        self.llm = Script(*steps)

    def ask_stream(self, q, session, snippets, instructions, **kw):
        yield "An answer."


def asker(*steps, **acts):
    events, spoken, traces = [], [], []
    ask_mod.now_ms = lambda: NOW
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=FakeJimmy(*steps),
                      actions={"state": lambda: {}, "trace": traces.append, **acts})

    def say(text):
        events.clear()
        a.hear(NOW, "mic", text, NOW - 1500)
        assert a.wait_idle(10), text
        return list(events)
    return a, say, spoken, traces


def test_through_the_asker_with_a_trace():
    mem = Memory(":memory:")
    a, say, spoken, traces = asker(call("list_reminders"), reminders=mem.reminders, remind=mem.add_reminder,
                                   agent_controls=lambda: [], agent_window=lambda: ("", "", None),
                                   traces=lambda n: [dict(t, steps=t.get("steps") or []) for t in reversed(traces)][:n])
    say("Jimmy, could you tell me which reminders are pending")
    assert spoken[-1] == "No reminders.", spoken
    t = traces[-1]
    assert t["via"] == "name" and t["route"].startswith("agent") and t["steps"][0]["tool"] == "list_reminders"
    assert t["said"] == "No reminders." and t["ms"] >= 0
    say("Jimmy, what did you just do")
    assert "could you tell me which reminders are pending" in spoken[-1] and "list reminders" in spoken[-1], spoken[-1]
    print("ok  through the Asker: the agent's tool runs the real command; every request leaves a trace")


def test_agent_failure_falls_back_to_the_rules():
    class Broken(Script):
        def chat_tools(self, *a, **k):
            raise RuntimeError("503")
    a, say, spoken, traces = asker()
    a._jimmy.llm = Broken()
    a._jimmy.llm.chat = lambda *x, **k: '{"tool": "answer", "args": {}}'
    say("Jimmy, what was the form on friday")
    assert spoken and a._agent_down_until > NOW, "it still answers, and the agent rests a minute"
    print("ok  the agent failing never silences Jimmy: the D41 path answers")


def test_a_failure_mid_task_ends_it_with_words():
    """2026-10-03: the model failed while Jimmy waited for the user's reply to its
    question; the exception killed the ask thread and nothing was said."""
    class Dies(Script):
        def chat_tools(self, messages, tools, **kw):
            if self.steps:
                return super().chat_tools(messages, tools, **kw)
            raise KeyError("choices")
    ag = Agent(Dies(call("ask_user", question="Which tab?")), env([]))
    assert ag.start("close the tab").kind == "await"
    out = ag.answer(None, "the second one")
    assert out.kind == "error" and out.say and ag.task is None
    print("ok  a failure mid-task ends the task with a spoken line, not a dead thread")


def test_calls_by_app_name_survive():
    import ambient.audio as audio
    from ambient.bus import ContextBus
    mem = Memory(":memory:")
    b = ContextBus.__new__(ContextBus)
    real = audio._holders
    try:
        audio._holders = lambda cap: [("C:#Apps#Discord.exe", 5)]
        assert b.not_a_call_app(mem, "Discord").startswith("Okay: Discord won't count")
        assert audio.mic_holders() == [] and json.loads(mem.setting("not_call_apps")) == ["discord"]
        audio._holders = lambda cap: [("C:#Apps#Discord.exe", 99)]
        assert audio.mic_holders() == [], "by name: taking the mic again doesn't bring it back (D40's did)"
    finally:
        audio._holders = real
        audio.NOT_CALL_APPS.clear()
    assert ask_mod.command("Don't consider Discord as call")[0] == "notcall"
    a, say, spoken, _ = asker(eye_contact=lambda x, y: True, call=lambda: ["Discord"],
                              not_a_call_app=lambda app: f"Okay: {app} won't count as a call.")
    say("Discord is not a call")
    assert spoken[-1] == "Okay: Discord won't count as a call.", "said without the name, during the 'call'"
    print("ok  calls: 'Discord isn't a call' by name, kept; it works without the name even during the call")


def test_the_wiki():
    from jimmy import wiki
    with tempfile.TemporaryDirectory() as d:
        root, mem = Path(d), Memory(":memory:")
        mem.add_goal("finish the essay")
        mem.remember("my sister Priya studies medicine")
        wiki.code_pages(mem, None, root=root)
        idx = wiki.index_text(root)
        assert "[Goals](me/goals.md)" in idx and "Things the user told Jimmy" in idx
        page = wiki.read("me/remembered.md", root)
        assert "verified: human:user" in page and "- my sister Priya studies medicine" in page
        assert wiki.read("../../secret.txt", root).startswith("No page"), "only pages inside the bundle"

        class Model:
            configured, model = True, "test-model"

            def chat(self, msgs, **kw):
                assert "<material>" in msgs[1]["content"] and "Priya" in msgs[1]["content"]
                return json.dumps({"pages": [{"type": "person", "title": "Priya", "description": "sister",
                                              "body": "- studies medicine", "sources": ["memories"]}]})
        assert wiki.model_pages(mem, None, Model(), root=root) == 1
        p = next(x for x in wiki.pages(root) if x["path"] == "people/priya.md")
        assert p["verified"] == "unverified" and p["generated"] == "model:test-model"
        assert "(unconfirmed)" in wiki.index_text(root)
        wiki.verify("people/priya.md", root)
        assert "(unconfirmed)" not in wiki.index_text(root)
        wiki.model_pages(mem, None, Model(), root=root)
        assert next(x for x in wiki.pages(root) if x["path"] == "people/priya.md")["verified"] == "human:user", \
            "a recompile keeps what you confirmed"
        assert wiki.delete("people/priya.md", root) and "Priya" not in wiki.index_text(root)
    print("ok  the wiki (OKF): code pages, model pages unconfirmed until you say, index, safe reads")


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
