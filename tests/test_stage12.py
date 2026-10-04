"""One runnable check for D45: the live session of 2026-10-05. `python tests/test_stage12.py`.
No network (models are scripted), no webcam, no mic; UI Automation and windows are faked.
Each check is a miss from that session, as the report quotes it."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import threading
import time
import types
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.agent as agent_mod  # noqa: E402
import ambient.ask as ask_mod  # noqa: E402
from ambient import act  # noqa: E402
from ambient.agent import Agent  # noqa: E402
from ambient.db import Store  # noqa: E402
from jimmy.memory import Memory  # noqa: E402

NOW = int(datetime(2026, 10, 5, 2, 10).timestamp() * 1000)
T = act.Target
# No waiting for windows to react in a test, without touching the real time module.
agent_mod.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)
real_now = ask_mod.now_ms


def call(tool: str, /, **args) -> dict:
    return {"tool_calls": [{"id": f"c{tool}", "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(args)}}], "content": ""}


class Script:
    """A model that answers each step from a list, and keeps what it was shown."""
    configured = True

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def chat_tools(self, messages, tools, **kw):
        self.seen.append([dict(m) for m in messages])
        step = self.steps.pop(0) if self.steps else {"content": "Done.", "tool_calls": []}
        return step(messages) if callable(step) else step


RESULTS = [T("Search", "EditControl", (100, 100, 400, 130), frozenset({"value"}), hwnd=1),
           T("Guest", "ButtonControl", (500, 100, 560, 130), frozenset({"invoke"}), hwnd=1),
           T("Images", "HyperlinkControl", (100, 160, 160, 180), frozenset({"invoke"}), hwnd=1),
           T("Add", "ButtonControl", (600, 100, 640, 130), frozenset({"invoke"}), hwnd=1)]


def env(did: list, screen=RESULTS, **more):
    e = {"window": lambda: ("Chrome", "Google", (0, 0, 1000, 600)), "controls": lambda: list(screen),
         "status": lambda: "Jimmy, live.", "wiki_index": lambda: "(empty)", "wiki": lambda p: "",
         "lists": lambda: "", "conversation": lambda: "", "look": lambda q, t: did.append(("look", q)) or "a picture",
         "search": lambda q: "", "open_app": lambda n: f"Opening {n}.",
         "close_app": lambda n: did.append(("close_app", n)) or f"Closed {n}.",
         "open_url": lambda u: f"Opened {u}.", "cursor": lambda t, a: did.append(("cursor", a, t.name)),
         "perform": lambda t, text: did.append(("perform", t.name, text)) or f"Done: {t.name}.",
         "submit": lambda t: did.append(("submit", t.name)) or f"Searched in {t.name}.",
         "progress": lambda s: did.append(("progress", s))}
    e.update(more)
    return e


class FakeJimmy:
    def __init__(self, llm):
        self.llm = llm
        self.asked = []

    def ask_stream(self, q, session, snippets, instructions, **kw):
        self.asked.append((q, snippets, instructions))
        yield "\n\nAn answer."


def asker(llm=None, clock=None, **acts):
    events, spoken, traces = [], [], []
    clock = clock or [NOW]
    ask_mod.now_ms = lambda: clock[0]
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=FakeJimmy(llm or Script()),
                      actions={"state": lambda: {}, "trace": traces.append, **acts})

    def say(text, ts_start=None, ts_end=None):
        events.clear()
        took = a.hear(ts_end or clock[0], "mic", text, ts_start or clock[0] - 1500)
        assert a.wait_idle(10), text
        return took
    return a, say, events, spoken, traces


# --- P0 ------------------------------------------------------------------------------

def test_p0_1_each_request_keeps_its_own_trace():
    """02:12:13: two traces with one timestamp and swapped outcomes; long requests logged
    under a later utterance. Now a second request can't write into the first's trace."""
    go = threading.Event()

    def blocked(messages):
        go.wait(5)
        return call("reply", text="A done.")
    did = []
    a, say, events, spoken, traces = asker(Script(blocked), pause=lambda m: did.append(("pause", m)),
                                           agent_controls=lambda: [], agent_window=lambda: ("", "", None))
    a.hear(NOW, "mic", "Jimmy, suggest me a video from my history", NOW - 1500)
    time.sleep(0.3)                                    # the first request now holds the lock, in the model
    a.hear(NOW, "mic", "Jimmy, pause for 5 minutes", NOW - 1500)
    time.sleep(0.3)                                    # ...and the second one waits behind it
    go.set()
    assert a.wait_idle(10)
    assert len(traces) == 2, traces
    by = {t["heard"]: t for t in traces}
    first, second = by["suggest me a video from my history"], by["pause for 5 minutes"]
    assert first["route"].startswith("agent") and first["said"] == "A done.", first
    assert second["route"] == "command" and second["said"] == "Paused for 5 minutes.", second
    assert second["wait_ms"] >= 200 and first["wait_ms"] < 200, "waiting for the lock is counted apart"
    print("ok  P0-1: each request keeps its own trace; time waiting apart from time working")


def test_p0_2a_windows_count_from_when_you_started_speaking():
    """02:16:13 "Jimmy?" -> 02:16:17 a long request, decoded after the 8 s window: dropped."""
    clock = [NOW]
    opened = []
    a, say, events, spoken, traces = asker(clock=clock, voice_on=lambda: False)
    assert say("Jimmy?") and a.listen_until == NOW + 8000
    a.ask = lambda q, source="typed", force=None: opened.append(q)    # just see what's taken
    clock[0] = NOW + 10_600                            # 3 s after the name it began; 7 s long; decoded now
    assert a.hear(NOW + 10_000, "mic", "Search my name on address bar and go to images", NOW + 3000)
    assert opened == ["Search my name on address bar and go to images"]
    a.listen_until = NOW + 8000
    assert not a.hear(NOW + 13_000, "mic", "and then we went home", NOW + 11_000), "begun after it closed: talk"
    a.followup_until = NOW + 20_000                    # the same rule for the follow-up window
    clock[0] = NOW + 26_000
    assert a.hear(NOW + 25_500, "mic", "and what about yesterday", NOW + 19_500)
    print("ok  P0-2a: a request begun inside its window is taken, however long it ran")


def test_p0_2b_the_call_rule_says_so_once_a_minute():
    clock = [NOW]
    a, say, events, spoken, traces = asker(clock=clock, eye_contact=lambda x, y: True, call=lambda: ["Discord"])
    assert not say("what's on my screen")
    heard = [e for e in events if e["type"] == "heard"]
    assert heard and "call" in heard[0]["skip"] and "not on a call" in heard[0]["hint"], events
    clock[0] += 20_000
    assert not say("can you tell me the time") and not [e for e in events if e["type"] == "heard"], "once a minute"
    clock[0] += 61_000
    assert not say("what time is it now") and [e for e in events if e["type"] == "heard"]
    print("ok  P0-2b: on a call, a no-name request says why it wasn't taken, and the way out")


def test_p0_2c_timmy_is_jimmy():
    p = ask_mod.parse_wake
    assert p("Timmy, close the UI") == "close the UI" and ask_mod.command("close the UI")[0] == "close_ui"
    assert p("Timmy, remove your eyes.") == "remove your eyes" and p("Jimmy's, open the timeline") == "open the timeline"
    assert p("talk to Timmy about it") is None and p("I told Timmy yesterday") is None
    print("ok  P0-2c: 'Timmy' and 'Jimmy's' wake Jimmy; Timmy in a sentence doesn't")


class Slow:
    """A model whose steps take as long as the test says; `tool_fallback` names a second."""
    configured = True

    def __init__(self, primary_s: float, fallback_s: float):
        self.wait = {None: primary_s, "backup-model": fallback_s}
        self.calls = []

    def tool_fallback(self):
        return "backup-model"

    def chat_tools(self, messages, tools, model=None, **kw):
        self.calls.append(model)
        threading.Event().wait(self.wait[model])
        return call("reply", text=f"from {model or 'primary'}")


def test_p0_3_a_slow_model_is_said_and_the_fallback_tried():
    """Steps of 10-30 s with nothing shown. Now: the fallback past the limit, then a line."""
    saved = agent_mod.STEP_TIMEOUT_S, agent_mod.SLOW_GIVE_UP_S
    agent_mod.STEP_TIMEOUT_S, agent_mod.SLOW_GIVE_UP_S = 0.2, 3.0
    try:
        slow, steps = [], []
        llm = Slow(5, 0.05)                              # the primary hangs; the fallback is quick
        ag = Agent(llm, env([], slow=lambda: slow.append(1), step=steps.append))
        out = ag.start("what's on this page")
        assert out.say == "from backup-model" and llm.calls == [None, "backup-model"] and not slow
        llm = Slow(0.7, 5)                               # both slow; the primary answers at last
        ag = Agent(llm, env([], slow=lambda: slow.append(1)))
        out = ag.start("what's on this page")
        assert out.say == "from primary" and slow == [1], "past both limits the user hears it's slow"
        llm = Slow(5, 5)                                 # nothing answers: the step gives up, with words
        agent_mod.SLOW_GIVE_UP_S = 0.6
        try:
            Agent(llm, env([])).start("what's on this page")
            raise AssertionError("no answer must fail the step")
        except TimeoutError:
            pass
        # model time and tool time apart, in the trace
        did = []
        ag = Agent(Script(call("plan", steps=["type it", "search"]), call("type_text", id=1, name="Search",
                                                                              text="carryminati"),
                          call("done", summary="Typed.")), env(did, step=steps.append))
        ag.start("search carryminati")
        ag.answer(True)
        typed = next(s for s in ag.last_steps if s["tool"] == "type_text")
        assert "ms" in typed and "tool_ms" in typed, typed
        assert any(s and s.startswith("Step 1 of 2") for s in steps), "an approved plan's step shows on the pill"
    finally:
        agent_mod.STEP_TIMEOUT_S, agent_mod.SLOW_GIVE_UP_S = saved
    print("ok  P0-3: a slow step asks the fallback, then says the model is slow; model and tool time apart")


def test_p0_3_stop_and_still_working():
    """"Go ahead with the plan", said 30 s after the yes that had started it; "stop" waited
    behind the running request. Now stop stops it, and a repeat hears what's running."""
    release = threading.Event()

    def hangs(messages):
        release.wait(5)
        return call("reply", text="Here you go.")
    hush = []
    a, say, events, spoken, traces = asker(Script(hangs), hush=lambda: hush.append(1),
                                           agent_controls=lambda: [], agent_window=lambda: ("", "", None))
    a.hear(NOW, "mic", "Jimmy, suggest me a video", NOW - 1500)
    time.sleep(1.7)                                    # running for a while now
    events.clear()
    a.hear(NOW, "mic", "Jimmy, suggest me a video", NOW - 1500)
    toast = [e for e in events if e["type"] == "toast"]
    assert toast and toast[0]["text"].startswith("Still working on: suggest me a video"), events
    assert spoken[-1] == "Still working on that." and a.busy == 1, "a repeat is dropped, said aloud"
    events.clear()
    a.hear(NOW, "mic", "Jimmy, stop", NOW - 1500)
    assert a.agent.cancelled and hush, "stop reaches the running agent at once"
    assert a.wait_idle(10)
    assert "Here you go." not in spoken and {"type": "toast", "text": "Okay.", "icon": "hush"} in events, events
    release.set()
    print("ok  P0-3: 'stop' stops a running task now; a repeat hears 'Still working on …'")


# --- P1 ------------------------------------------------------------------------------

def test_p1_1_a_feature_inside_a_plan_goes_on():
    """02:29: plan type -> Enter -> click Images. After Enter the model scrolled, Jimmy said
    "Scrolling down", and the task ended. Now the scroll runs and the plan goes on."""
    did, ran = [], []
    llm = Script(call("plan", steps=["type my name", "press Enter", "click Images"]),
                 call("type_text", id=1, name="Search", text="my name"), call("submit", id=1, name="Search"),
                 call("scroll", dir="down"), call("click", id=4, name="Images"), call("done", summary="Images are up."))
    ag = Agent(llm, env(did, feature=lambda n, a: ran.append((n, a)) or "Scrolling down"))
    assert ag.start("search my name and go to images").kind == "await"
    out = ag.answer(True)
    assert out.kind == "done" and out.say == "Images are up.", out
    assert ran == [("scroll", {"dir": "down"})]
    assert [d[1] for d in did if d[0] in ("perform", "submit")] == ["Search", "Search", "Images"], did
    assert "Scrolling down\nScreen now:" in llm.seen[4][-1]["content"], "the feature's line fed the next step"
    # ...and through the real Asker, the feature is the same code a spoken scroll runs
    a, say, events, spoken, traces = asker()
    assert a._feature("scroll", {"dir": "down"}) == "Scrolling down"
    assert {"type": "ui", "action": "scroll", "dir": "down"} in events and not spoken
    assert a._feature("draft", {}) is None, "a draft needs the answer flow: the plan hands back"
    print("ok  P1-1: Jimmy's own feature inside an approved plan runs, and the plan goes on")


def test_p1_1_a_plan_that_stops_says_what_didnt_run():
    llm = Script(call("plan", steps=["type it", "press Enter", "click Images"]),
                 call("type_text", id=1, name="Search", text="carryminati"),
                 *[call("find_controls", text="enter") for _ in range(5)])
    ag = Agent(llm, env([]))
    ag.start("search carryminati and open images")
    saved = agent_mod.MAX_STEPS
    agent_mod.MAX_STEPS = 2
    try:
        out = ag.answer(True)
    finally:
        agent_mod.MAX_STEPS = saved
    assert out.kind == "error" and "I didn't get to: 2. press Enter. 3. click Images." in out.say, out.say
    print("ok  P1-1: a plan that ends early says which steps didn't run")


def test_p1_2_find_controls_finds_only_what_fits():
    """find_controls("Images") -> [14] Guest, three times; ("address") -> [18] Add."""
    t = agent_mod.Task("go to images", [], agent_mod.reading_order(RESULTS))
    ag = Agent(Script(), env([]))
    hit = ag._find(t, "images")
    assert '"Images"' in hit and "Guest" not in hit, hit
    miss = ag._find(t, "address")
    assert miss.startswith("Nothing like that in this window") and '"Add"' in miss.split("Nearby")[1], miss
    assert "[" not in miss.split("Nearby")[0], "nothing offered as a match"
    later = RESULTS + [T("Videos", "HyperlinkControl", (200, 160, 260, 180), frozenset({"invoke"}), hwnd=1)]
    ag = Agent(Script(), env([], screen=later))
    got = ag._find(t, "videos")
    assert got.startswith("(The screen changed") and '"Videos"' in got, "read again after the page loaded"
    print("ok  P1-2: find_controls uses the 0.45 bar, reads a changed screen again, and offers what's near")


def test_p1_3_a_lone_action_ends_and_stale_numbers_are_refused():
    did = []
    screen = [T("Maximize", "ButtonControl", (900, 0, 930, 30), frozenset({"invoke"}), hwnd=1),
              T("New Tab", "ButtonControl", (100, 0, 130, 30), frozenset({"invoke"}), hwnd=1)]
    llm = Script(call("click", id=2, name="Maximize"), call("click", id=1, name="New Tab"))
    ag = Agent(llm, env(did, screen=screen))
    out = ag.start("maximize the window")
    assert out.kind == "await" and "Maximize" in out.say
    out = ag.answer(True)
    assert out.kind == "done" and out.say == "Done: Maximize." and len(llm.seen) == 1, "no further turn"
    assert ag.task is None and not [d for d in did if d[0] == "progress"], "said once, as the answer"
    shifted = [screen[1], screen[0]]                    # after the maximize, [1] is New Tab
    llm = Script(call("click", id=1, name="Maximize"), call("reply", text="It's maximized."))
    ag = Agent(llm, env([], screen=shifted))
    out = ag.start("maximize it")
    assert out.say == "It's maximized." and "Control 1 is now “New Tab”" in llm.seen[1][-1]["content"]
    print("ok  P1-3: a lone action ends after it's done; a number that now means another control is refused")


def test_p1_4_yes_answers_jimmys_own_question():
    """02:09:11 "Do you want me to maximize the window?" -> "Yes." -> "Nothing to confirm.\""""
    llm = Script(call("ask_user", question="Do you want me to maximize the window?"),
                 call("done", summary="Maximized."))
    a, say, events, spoken, traces = asker(llm, agent_controls=lambda: [], agent_window=lambda: ("", "", None))
    say("Jimmy, maximize the window")
    assert spoken[-1] == "Do you want me to maximize the window?"
    assert say("Yes.")
    assert spoken[-1] == "Maximized." and "Nothing to confirm." not in spoken, spoken
    assert llm.seen[-1][-1]["content"] == "The user said: Yes." and traces[-1]["route"] == "agent: your answer"
    assert "Never ask_user \"do you want me to <action>?\"" in agent_mod.SYSTEM
    print("ok  P1-4: 'Yes.' to Jimmy's own question is the answer, not 'Nothing to confirm.'")


def test_p1_5_clicking_a_text_box_focuses_it():
    """02:17:07: "I can't press “Address and search bar” without your mouse.\""""
    focused = []

    class Auto:
        class PatternId:
            InvokePattern, TogglePattern, SelectionItemPattern, ExpandCollapsePattern, ValuePattern = range(5)

    class Box:
        def GetPattern(self, pid):
            return object() if pid == Auto.PatternId.ValuePattern else None

        def SetFocus(self):
            focused.append(True)
    assert act.press(Box(), "Address and search bar", None, Auto) == "Focused “Address and search bar”."
    assert focused == [True]
    print("ok  P1-5: 'click' on a box with only Value puts the cursor in it (UI Automation, no mouse)")


def test_p1_6_windows_minimize_never_closes():
    """"Maximize the window and minimize the VS code" -> "Do you want me to close VS Code?\""""
    did = []
    llm = Script(call("window_state", name="VS Code", state="minimize"), call("done", summary="Minimized."))
    ag = Agent(llm, env(did, window_state=lambda n, s: did.append(("state", n, s)) or f"{s.capitalize()}d {n}."))
    out = ag.start("minimize the vs code")
    assert out.kind == "await" and out.say == "Minimize VS Code? Say yes.", out.say
    out = ag.answer(True)
    assert ("state", "VS Code", "minimize") in did and not [d for d in did if d[0] == "close_app"]
    assert out.say == "Minimized VS Code.", "a lone action ends with what it did"
    ag = Agent(Script(call("list_windows"), call("reply", text="Chrome and VS Code.")),
               env([], windows=lambda: [("Chrome", "YouTube"), ("VS Code", "agent.py")]))
    assert ag.start("what's running on my pc").say == "Chrome and VS Code."
    assert "VS Code — agent.py" in ag.last_steps[0]["result"]
    wins = [(1, "Code.exe", "agent.py - Visual Studio Code", "Chrome_WidgetWin_1"),
            (2, "chrome.exe", "YouTube - Google Chrome", "Chrome_WidgetWin_1"),
            (3, "Spotify.exe", "Spotify Premium", "Chrome_WidgetWin_0")]
    assert act.pick_window("vs code", wins)[0] == 1 and act.pick_window("Chrome", wins)[0] == 2
    assert act.pick_window("rome", wins)[0] == 2, "a misheard name, by sound, among the open apps"
    assert act.pick_window("notepad", wins) is None
    assert "Minimize is never close" in agent_mod.SYSTEM and "window_state" in agent_mod.UI_TOOLS
    print("ok  P1-6: list, switch, minimize/maximize by app name; minimize is never close")


def test_p1_7_a_tray_popup_is_not_the_window():
    from ambient import screen
    from ambient.bus import ContextBus, Counters
    b = ContextBus.__new__(ContextBus)
    b.counters = Counters()
    tray = screen.ActiveWindow(5, "explorer.exe", "System tray overflow window.", "NotifyIconOverflowWindow")
    chrome = screen.ActiveWindow(7, "chrome.exe", "Google", "Chrome_WidgetWin_1")
    saved = screen.active_window, getattr(screen.user32, "IsWindow", None)
    try:
        screen.active_window = lambda: tray
        screen.user32.IsWindow = lambda h: 1
        b._last_app = chrome
        assert b.agent_aw() == chrome, "the agent acts on the last real window"
        assert b._tick() == "shell" and b.counters.skipped_shell == 1, "and capture skips the popup"
        screen.active_window = lambda: chrome
        assert b.agent_aw() == chrome
    finally:
        screen.active_window = saved[0]
        if saved[1] is not None:
            screen.user32.IsWindow = saved[1]
    assert screen.is_shell(screen.ActiveWindow(1, "explorer.exe", "System tray overflow window", ""))
    print("ok  P1-7: a tray popup in front: the agent uses the last app window, and nothing is captured")


def test_p1_8_lines_cut_in_half_are_joined():
    from ambient.audio import Joiner, dangles
    j = Joiner(gap_ms=1200)
    assert j.feed(0, 1000, "mic", "Can you close") == [] and dangles("Suggest me a video from.")
    j.started("mic", 1600)
    assert j.feed(1700, 2600, "mic", "cloud code?") == [(0, 2600, "mic", "Can you close cloud code?")]
    assert j.feed(5000, 6000, "mic", "maximize the window and") == []
    assert j.due(6500) == [], "still within the gap"
    assert j.due(7300) == [(5000, 6000, "mic", "maximize the window and")], "nobody went on: it goes alone"
    assert j.feed(9000, 9500, "mic", "Close.") == [(9000, 9500, "mic", "Close.")], "a lone word isn't held"
    j.feed(10_000, 11_000, "mic", "open the")
    assert j.nothing("mic") == [(10_000, 11_000, "mic", "open the")], "what followed was noise: it goes alone"
    assert ask_mod.nav("Scroll down and maximize the window.") is None, "a second instruction: not a scroll"
    assert ask_mod.nav("scroll down and show me older things")["action"] == "scroll", "D35's case stays"
    assert ask_mod.nav("Can you close") is None and ask_mod.nav("close")["action"] == "close"
    print("ok  P1-8: a line cut at 'and'/'close' waits for the rest; 'can you close' isn't 'close'")


def test_p1_9_the_console_is_kept_without_captured_text():
    from ambient import logs
    saved = sys.stdout, sys.stderr
    with tempfile.TemporaryDirectory() as d:
        try:
            sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
            path = logs.install(Path(d))
            print("[ask] no name needed (eye contact): 'search my secret project on youtube'")
            print("[card] RECALL: Same Northwind Fellowship as Tue 15:02   (moment end)")
            print("[jimmy] key nvapi-abcdefghijklmnopqrstuvwxyz")
            print("[bus] resumed by pill")
            sys.stdout.flush()
            for h in logs.logging.getLogger("jimmy.console").handlers:
                h.flush()
            text = path.read_text(encoding="utf-8")
        finally:
            sys.stdout, sys.stderr = saved
            for h in list(logs.logging.getLogger("jimmy.console").handlers):
                h.close()
                logs.logging.getLogger("jimmy.console").removeHandler(h)
    assert "[bus] resumed by pill" in text and "eye contact): <35 chars>" in text, text
    assert "secret" not in text and "Northwind" not in text and "nvapi-" not in text, text
    h = logs.RotatingFileHandler
    assert logs.MAX_BYTES == 2_000_000 and logs.BACKUPS == 4 and h
    print("ok  P1-9: the console goes to data/logs/jimmy.log, rotated, with no captured text or keys")


# --- P2 ------------------------------------------------------------------------------

def test_p2_1_who_resumed_is_logged():
    from ambient.api import _by
    from ambient.bus import ContextBus
    b = ContextBus.__new__(ContextBus)
    b._gate_memory = mem = Memory(":memory:")
    b.paused_until = 0
    out = io.StringIO()
    saved = sys.stdout
    try:
        sys.stdout = out
        b.pause(10, "command")
        b.resume("pill")
    finally:
        sys.stdout = saved
    assert "paused for 10 min by command" in out.getvalue() and "resumed by pill" in out.getvalue()
    rows = mem.traces(5)
    assert [(r["route"], r["via"]) for r in rows] == [("resume", "pill"), ("pause", "command")]
    got = []
    _by(lambda by="?": got.append(by), by="hotkey")
    _by(lambda: got.append("none"), by="hotkey")
    assert got == ["hotkey", "none"], "the source reaches hooks that ask for it"
    print("ok  P2-1: pause and resume say who did it, in the console and the decision log")


def test_p2_2_whisper_hears_the_open_apps():
    from ambient import audio
    p = audio.app_prompt(["Chrome", "Claude", "VS Code"], ["Video - YouTube - Google Chrome", "notes.txt"])
    assert p == "Jimmy, Chrome, Claude, VS Code, YouTube.", p
    assert audio.echoes_prompt("Jimmy, Chrome, Claude.", p) and not audio.echoes_prompt("Jimmy", p)
    assert not audio.echoes_prompt("close Chrome", p)
    seen = {}

    class Model:
        def __init__(self, text):
            self.text = text

        def transcribe(self, audio_, language=None, **opts):
            seen.update(opts)
            seg = types.SimpleNamespace(text=self.text, no_speech_prob=0.1, avg_logprob=-0.2)
            return [seg], types.SimpleNamespace(language="en", all_language_probs=[("en", 0.9)])
    import numpy as np
    tr = audio.Transcriber.__new__(audio.Transcriber)
    tr.prompt, tr.model = p, Model("Can you close Claude?")
    loud = (np.sin(np.linspace(0, 400, 16000)) * 8000).astype(np.int16)
    assert tr.transcribe(loud) == "Can you close Claude?" and seen["initial_prompt"] == p
    tr.model = Model(" Jimmy, Chrome, Claude, VS Code, YouTube.")
    assert tr.transcribe(loud) == "", "the prompt echoed back from noise is dropped"
    assert "\"room\", \"Roam\"" in agent_mod.SYSTEM and "<open>" in agent_mod.SYSTEM
    ctx = Agent(Script(), env([], open_apps=lambda: ["Chrome", "Claude"])).context("close room", [])
    assert "<open>\nChrome, Claude\n</open>" in ctx[1]["content"]
    print("ok  P2-2: Whisper is told the open apps; an echo of that list is dropped; the agent sees them")


def test_p2_3_one_question_per_request():
    llm = Script(call("ask_user", question="Which tab?"), call("ask_user", question="Which tab, again?"),
                 call("reply", text="Closing the current tab."))
    ag = Agent(llm, env([]))
    assert ag.start("close roam tab").say == "Which tab?"
    out = ag.answer(None, "the one which is right now")
    assert out.say == "Closing the current tab." and "already asked once" in llm.seen[2][-1]["content"]
    assert "\"the current tab\" in a browser is the selected tab" in agent_mod.SYSTEM
    print("ok  P2-3: at most one ask_user per request; then the best guess (still confirmed)")


def test_p2_4_a_new_request_isnt_an_answer():
    nr = ask_mod.new_request
    assert nr("can you listen", "Do you want me to click the address bar?")
    assert nr("minimize chrome, minimize vs code", "Do you want me to close VS Code?")
    assert nr("pause for 10 minutes", "Which tab?")
    assert not nr("Yes.", "Do you want me to maximize?") and not nr("the second one", "Which tab?")
    assert not nr("close the second one", "Which tab?"), "an answer to 'which' may use a verb"
    llm = Script(call("ask_user", question="Do you want me to click the address bar?"),
                 call("reply", text="Yes, I'm listening."))
    a, say, events, spoken, traces = asker(llm, agent_controls=lambda: [], agent_window=lambda: ("", "", None))
    say("Jimmy, go to the search bar")
    say("can you listen")
    assert spoken[-1] == "Yes, I'm listening." and traces[-1]["route"].startswith("agent (rules"), traces[-1]
    assert "The user said" not in llm.seen[-1][-1]["content"], "a new task, not an answer"
    assert agent_mod.ASK_TTL_S == 60
    print("ok  P2-4: a new request while Jimmy waits for an answer starts afresh; questions wait 60 s")


def test_p2_5_a_control_you_refused_isnt_offered_again():
    """"Click on YouTube India" -> "Press “You”?" -> No -> the same request -> "You" again."""
    screen = [T("You", "ButtonControl", (900, 10, 930, 40), frozenset({"invoke"}), hwnd=1),
              T("Home", "HyperlinkControl", (100, 10, 200, 40), frozenset({"invoke"}), hwnd=1)]
    ag = Agent(Script(call("click", id=2, name="You")), env([], screen=screen))
    assert "You" in ag.start("click on youtube india").say
    assert ag.answer(False).say == "Okay, I won't."
    llm = Script(call("click", id=2, name="You"), call("look_at_screen", question="where is YouTube India?"),
                 call("reply", text="I can't see YouTube India here."))
    ag.llm = llm
    out = ag.start("click on youtube india")
    assert '<rejected>\n"You"\n</rejected>' in llm.seen[0][1]["content"]
    assert "said no to \u201cYou\u201d" in llm.seen[1][-1]["content"] and out.say == "I can't see YouTube India here."
    assert "@x,y" in agent_mod.SYSTEM
    print("ok  P2-5: a control you said no to is in <rejected> and refused for two minutes")


def test_p2_6_why_did_you_say_that():
    llm = Script()
    a, say, events, spoken, traces = asker(llm, agent_controls=lambda: [], agent_window=lambda: ("", "", None))
    a.turns.append({"q": "suggest me a video", "a": "Try the PUBG India stream from Tuesday.", "mode": "chat",
                    "query": "suggest me a video", "ts": NOW})
    assert ask_mod.route("why do you suggested me that?", a.turns[-1], NOW)[0] == "why"
    say("Jimmy, why do you suggested me that?")
    q, snippets, style = a._jimmy.asked[-1]
    assert style == ask_mod.WHY_STYLE and "PUBG India" in snippets[0].text and not llm.seen, "chat, no agent"
    assert ask_mod.route("why do you suggested me that?", None, NOW)[0] != "why", "only with a last answer"
    print("ok  P2-6: 'why did you suggest that?' is answered from Jimmy's own last answer")


def test_p2_7_answers_never_start_with_a_blank_line():
    a, say, events, spoken, traces = asker()
    a.publish({"type": "answer_delta", "id": "x", "text": "\n"})
    a.publish({"type": "answer_delta", "id": "x", "text": "\nI see a VS Code window."})
    a.publish({"type": "answer_delta", "id": "x", "text": " More."})
    a.publish({"type": "answer_end", "id": "x", "text": "\nI see a VS Code window. More.\n"})
    assert [e["text"] for e in events] == ["I see a VS Code window.", " More.", "I see a VS Code window. More."]
    print("ok  P2-7: every answer is trimmed once, where all of them are published")


def test_p2_8_no_captchas_and_no_naming_people():
    did = []
    screen = [T("I'm not a robot", "CheckBoxControl", (100, 100, 120, 120), frozenset({"toggle"}), hwnd=1)]
    out = Agent(Script(call("click", id=1, name="I'm not a robot")), env(did, screen=screen)).start("tick it")
    assert out.say == agent_mod.NO_CAPTCHA and not [d for d in did if d[0] in ("perform", "cursor")]
    llm = Script(call("look_at_screen", question="who are these people in the thumbnail?"),
                 call("reply", text=agent_mod.NO_IDENTIFY))
    did = []
    out = Agent(llm, env(did)).start("search for me who these people are")
    assert out.say == agent_mod.NO_IDENTIFY and not [d for d in did if d[0] == "look"], "no picture sent"
    assert "Refused" in llm.seen[1][-1]["content"] and "Never identify people" in agent_mod.SYSTEM
    print("ok  P2-8: Jimmy never ticks a CAPTCHA and never says who someone is from a picture")


def test_p2_9_leaked_tokens_in_a_tool_name():
    name = "submit...??<|end|><|start|>assistant<|channel|>analysis"
    assert agent_mod.clean_tool_name(name) == "submit" and agent_mod.clean_tool_name("bogus<|x") == "bogus<|x"
    c = call("submit", id=1, name="Search")
    c["tool_calls"][0]["function"]["name"] = name
    out = Agent(Script(c), env([])).start("run the search")
    assert out.kind == "await" and out.say.startswith("Run the search in"), out.say
    print("ok  P2-9: a tool name with leaked chat tokens is cleaned to the tool it names")


def test_p2_10_a_bare_jimmy_is_answered():
    clock = [NOW]
    a, say, events, spoken, traces = asker(clock=clock)
    say("Jimmy?")
    assert spoken == ["Yes?"] and events[0] == {"type": "listening"}
    clock[0] += 10_000
    say("Jimmy?")
    assert spoken == ["Yes?"], "not again within 30 s"
    a2, say2, _, spoken2, _ = asker(voice_on=lambda: False)
    say2("Jimmy")
    assert spoken2 == [], "voice off: silent"
    print("ok  P2-10: a bare 'Jimmy?' gets a spoken 'Yes?' (at most every 30 s, voice permitting)")


def test_the_llm_client_names_a_fallback_and_takes_a_model():
    import httpx

    from jimmy import config as jcfg
    from jimmy.llm import LLM
    sent = []

    def handler(req):
        sent.append(json.loads(req.content)["model"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "done", "arguments": "{}"}}]}}]})
    llm = LLM(key="k", transport=httpx.MockTransport(handler))
    other = llm.tool_fallback()
    assert other and other != (llm.tools_model or llm.model), (other, llm.tools_model, llm.model)
    llm.chat_tools([{"role": "user", "content": "x"}], [])
    llm.chat_tools([{"role": "user", "content": "x"}], [], model=other)
    assert sent == [llm.tools_model or llm.model, other], sent
    print(f"ok  the LLM client ({jcfg.PROVIDER}): a fallback for slow agent steps, and a per-call model")


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
        finally:
            ask_mod.now_ms = real_now
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
