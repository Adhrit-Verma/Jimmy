"""One runnable check for D47–D51: the optimizations from docs/RESEARCH-AGENT-2026-10.md.
`python tests/test_stage13.py`. No network, no webcam, no mic; UI Automation, windows and
models are faked."""
from __future__ import annotations

import json
import sys
import threading
import time
import types
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.agent as agent_mod  # noqa: E402
import ambient.ask as ask_mod  # noqa: E402
from ambient import act, config, power  # noqa: E402
from ambient.agent import Agent  # noqa: E402
from ambient.db import Store  # noqa: E402

NOW = int(datetime(2026, 10, 7, 21, 0).timestamp() * 1000)
T = act.Target
agent_mod.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)
real_now = ask_mod.now_ms


def call(tool: str, /, **args) -> dict:
    return {"tool_calls": [{"id": f"c{tool}", "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(args)}}], "content": ""}


class Script:
    configured = True

    def __init__(self, *steps):
        self.steps, self.seen, self.tools_seen = list(steps), [], []

    def chat_tools(self, messages, tools, **kw):
        self.seen.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in tools])
        step = self.steps.pop(0) if self.steps else {"content": "Done.", "tool_calls": []}
        return step(messages) if callable(step) else step


SCREEN = [T("Search", "EditControl", (100, 100, 400, 130), frozenset({"value"}), hwnd=1),
          T("Images", "HyperlinkControl", (100, 160, 160, 180), frozenset({"invoke"}), hwnd=1)]


def env(did: list, screen=SCREEN, **more):
    e = {"window": lambda: ("Chrome", "Google", (0, 0, 1000, 600)), "controls": lambda: list(screen),
         "status": lambda: "Jimmy, live.", "wiki_index": lambda: "(empty)", "wiki": lambda p: "",
         "lists": lambda: "", "conversation": lambda: "", "look": lambda q, t: "a picture",
         "search": lambda q: "", "open_app": lambda n: f"Opening {n}.", "close_app": lambda n: f"Closed {n}.",
         "open_url": lambda u: f"Opened {u}.", "cursor": lambda t, a: did.append(("cursor", a, t.name)),
         "perform": lambda t, text: did.append(("perform", t.name, text)) or f"Done: {t.name}.",
         "submit": lambda t: did.append(("submit", t.name)) or f"Searched in {t.name}.",
         "progress": lambda s: did.append(("progress", s))}
    e.update(more)
    return e


# --- a fake UI Automation, enough for act.controls both ways ------------------------------

class _Rect:
    def __init__(self, l, t, r, b):
        self.left, self.top, self.right, self.bottom = l, t, r, b

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _El:
    def __init__(self, name, kind, rect, pats=(), password=False, offscreen=False, help_text="", parent=None):
        self.p = dict(name=name, kind=kind, rect=_Rect(*rect), pats=set(pats), password=password,
                      offscreen=offscreen, help=help_text)
        self.parent = parent
        self.CurrentIsPassword = self.CachedIsPassword = password
        self.CachedIsOffscreen, self.CachedName, self.CachedHelpText = offscreen, name, help_text
        self.CachedBoundingRectangle = self.p["rect"]
        self.CachedControlType = {"ButtonControl": 1, "EditControl": 2, "HyperlinkControl": 3,
                                  "TitleBarControl": 4}[kind]

    def GetCurrentPropertyValue(self, pid):
        return pid in self.p["pats"]

    GetCachedPropertyValue = GetCurrentPropertyValue


class _Ctrl:
    def __init__(self, el):
        self.Element, self.IsOffscreen, self.BoundingRectangle = el, el.p["offscreen"], el.p["rect"]
        self.Name, self.ControlTypeName = el.p["name"], el.p["kind"]

    def GetPropertyValue(self, pid):
        return self.Element.p["help"]

    def GetParentControl(self):
        return _Ctrl(self.Element.parent) if self.Element.parent else None


class _Found:
    def __init__(self, els):
        self.els, self.Length = els, len(els)

    def GetElement(self, i):
        return self.els[i]


@contextmanager
def fake_uia(elements, calls):
    title = _El("Title", "TitleBarControl", (0, 0, 1000, 30))
    for e in elements:
        if e.p["name"] == "Close" and e.parent is None:
            e.parent = title

    class Root:
        class Element:
            @staticmethod
            def FindAll(scope, cond):
                calls.append("FindAll")
                return _Found(elements)

            @staticmethod
            def FindAllBuildCache(scope, cond, cr):
                calls.append("FindAllBuildCache")
                return _Found(elements)

    class Uia:
        CreatePropertyCondition = staticmethod(lambda pid, v: pid)
        CreateOrCondition = staticmethod(lambda a, b: (a, b))
        CreateCacheRequest = staticmethod(lambda: types.SimpleNamespace(AddProperty=lambda pid: None))

    mod = types.ModuleType("uiautomation")
    mod.PropertyId = types.SimpleNamespace(**{n: n for n in (
        "NameProperty", "ControlTypeProperty", "BoundingRectangleProperty", "IsOffscreenProperty",
        "IsPasswordProperty", "HelpTextProperty", "IsInvokePatternAvailableProperty",
        "IsTogglePatternAvailableProperty", "IsSelectionItemPatternAvailableProperty",
        "IsExpandCollapsePatternAvailableProperty", "IsValuePatternAvailableProperty")})
    mod.ControlTypeNames = {1: "ButtonControl", 2: "EditControl", 3: "HyperlinkControl", 4: "TitleBarControl"}
    mod.ControlFromHandle = lambda h: Root
    mod.UIAutomationInitializerInThread = contextmanager(lambda: (yield))
    mod.Control = types.SimpleNamespace(CreateControlFromElement=_Ctrl)
    sub = types.ModuleType("uiautomation.uiautomation")
    sub._AutomationClient = types.SimpleNamespace(instance=lambda: types.SimpleNamespace(IUIAutomation=Uia))
    from ambient import screen
    saved = sys.modules.get("uiautomation"), sys.modules.get("uiautomation.uiautomation"), screen.wake_accessibility
    sys.modules["uiautomation"], sys.modules["uiautomation.uiautomation"] = mod, sub
    screen.wake_accessibility = lambda h: None
    try:
        yield
    finally:
        for k, v in (("uiautomation", saved[0]), ("uiautomation.uiautomation", saved[1])):
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        screen.wake_accessibility = saved[2]


# --- D47: the footprint ----------------------------------------------------------------

def test_d47_cached_controls_match_the_walk():
    P = "Is{}PatternAvailableProperty".format
    els = [_El("Search", "EditControl", (100, 100, 400, 130), {P("Value")}),
           _El("", "EditControl", (100, 140, 400, 170), {P("Value")}, help_text="Search Google"),
           _El("Images", "HyperlinkControl", (100, 160, 160, 180), {P("Invoke")}),
           _El("Close", "ButtonControl", (960, 0, 990, 30), {P("Invoke")}),
           _El("Hidden", "ButtonControl", (0, 0, 50, 50), {P("Invoke")}, offscreen=True),
           _El("Tiny", "ButtonControl", (0, 0, 2, 2), {P("Invoke")}),
           _El("Password", "EditControl", (100, 200, 400, 230), {P("Value")}, password=True)]
    calls = []
    with fake_uia(els, calls):
        walk, cached = act._controls_walk(1), act._controls_cached(1)
        assert act.controls(1) == cached and calls[-1] == "FindAllBuildCache", "UIA_CACHE is on by default"
    assert walk == cached, (walk, cached)
    assert [t.name for t in cached] == ["Search", "Search Google", "Images", "Close window", "Password"]
    assert cached[-1].password and cached[0].can == frozenset({"value"})
    print("ok  D47: one cached UI Automation query finds exactly what the old walk found")


def test_d47_unchanged_desktop_stops_before_the_password_check():
    from ambient import screen
    from ambient.bus import ContextBus, Counters
    from ambient.redact import Exclusions
    b = ContextBus.__new__(ContextBus)
    b.counters, b.exclusions, b._sensitive_key = Counters(), Exclusions(), None
    asked = []
    b.source = types.SimpleNamespace(grab=lambda timeout_ms=200: None)
    aw = screen.ActiveWindow(9, "code.exe", "agent.py - Jimmy", "Chrome_WidgetWin_1")
    saved = screen.active_window, screen.focused_is_password
    try:
        screen.active_window = lambda: aw
        screen.focused_is_password = lambda: asked.append(1) or False
        assert b._tick() == "no-frame" and len(asked) == 1, "first sight of the window: checked"
        b._tick_key = (aw.hwnd, aw.title)          # as a tick that got this far sets it
        assert b._tick() == "no-frame" and len(asked) == 1, "same window, nothing presented: no UIA call"
        aw2 = screen.ActiveWindow(9, "code.exe", "bus.py - Jimmy", "Chrome_WidgetWin_1")
        screen.active_window = lambda: aw2
        assert b._tick() == "no-frame" and len(asked) == 2, "a new title is checked again"
    finally:
        screen.active_window, screen.focused_is_password = saved
    print("ok  D47: an unchanged desktop costs no UI Automation call")


def test_d47_slower_ticks_when_idle_and_nothing_changes():
    from ambient.bus import ContextBus
    b = ContextBus.__new__(ContextBus)
    saved = power.user_idle_s
    try:
        power.user_idle_s = lambda: 120.0
        assert b._interval("no-frame") == config.IDLE_FRAME_INTERVAL_S
        assert b._interval("captured") == config.FRAME_INTERVAL_S, "a change: back to 2 s"
        power.user_idle_s = lambda: 5.0
        assert b._interval("no-frame") == config.FRAME_INTERVAL_S, "you're at the keyboard"
    finally:
        power.user_idle_s = saved
    print("ok  D47: the tick slows to 6 s only when you're idle and the screen is still")


def test_d47_power_helpers_never_stop_jimmy():
    assert power.background() in (True, False) and power.user_idle_s() >= 0
    saved = power.on_battery, power.cpu_busy
    try:
        power._cache.clear()
        power.on_battery, power.cpu_busy = (lambda: True), (lambda: False)
        assert power.constrained(), "on battery: optional work waits"
        power._cache.clear()
        power.on_battery = lambda: False
        assert not power.constrained()
        config.LOAD_AWARE = False
        power._cache.clear()
        power.on_battery = lambda: True
        assert not power.constrained(), "LOAD_AWARE off: never constrained"
    finally:
        config.LOAD_AWARE = True
        power.on_battery, power.cpu_busy = saved
        power._cache.clear()
    print("ok  D47: efficiency mode, battery and busy checks only ever make Jimmy lighter")


def test_d47_prompt_order_and_cache_hits():
    llm = Script({**call("reply", text="Hi."), "_usage": {"prompt": 4100, "cached": 3900}})
    ag = Agent(llm, env([]))
    ag.start("hello")
    user = llm.seen[0][1]["content"]
    assert user.index("<you>") < user.index("<lists>") < user.index("<status>") < user.index("<screen>") \
        < user.index("Request:"), "what changes least comes first"
    assert ag.last_steps[0]["cached"] == 3900 and ag.last_steps[0]["prompt"] == 4100
    print("ok  D47: the stable prefix comes first; each step records prompt and cached tokens")


# --- D48: the agent --------------------------------------------------------------------

def test_d48_a_step_sees_the_tools_its_words_point_at():
    import json as _json
    full = len(_json.dumps(agent_mod.TOOLS))
    small = agent_mod.select_tools("what's on my screen")
    assert len(small) == len(agent_mod.CORE) and len(_json.dumps(small)) < full / 2, "core only, under half"
    names = {t["function"]["name"] for t in agent_mod.select_tools("remind me at 5 to call mom")}
    assert {"remind", "list_reminders"} <= names and "curtain" not in names
    assert len(agent_mod.select_tools("मेरे रिमाइंडर दिखाओ")) == len(agent_mod.TOOLS), "Hindi: everything"
    llm = Script(call("more_tools", need="a countdown timer"), call("timer", seconds=300))
    out = Agent(llm, env([])).start("can you set one for five minutes")
    assert "timer" not in llm.tools_seen[0], "not shown at first"
    assert "timer" in llm.tools_seen[1] and out.data.get("action") == "timer", (llm.tools_seen, out)
    config.AGENT_TOOL_RETRIEVAL = False
    try:
        assert len(agent_mod.select_tools("what's on my screen")) == len(agent_mod.TOOLS)
    finally:
        config.AGENT_TOOL_RETRIEVAL = True
    print("ok  D48: the core tools plus the features a request names; more_tools for the rest")


def test_d48_every_action_is_checked():
    values = {"Search": "carryminati"}
    llm = Script(call("plan", steps=["type", "search"]), call("type_text", id=1, name="Search", text="carryminati"),
                 call("submit", id=1, name="Search"), call("done", summary="Done."))
    ag = Agent(llm, env([], value_of=lambda t: values.get(t.name)))
    ag.start("search carryminati")
    ag.answer(True)
    typed, sub = ag.last_steps[1], ag.last_steps[2]
    assert typed["check"].startswith("\u2713") and "\u2713 The box now holds" in llm.seen[2][-1]["content"]
    assert sub["check"].startswith("\u2717 Nothing changed"), "same title, same controls after Enter: said so"
    values["Search"] = "carry"
    llm = Script(call("plan", steps=["type"]), call("type_text", id=1, name="Search", text="carryminati"),
                 call("done", summary="Done."))
    ag = Agent(llm, env([], value_of=lambda t: values.get(t.name)))
    ag.start("type carryminati")
    ag.answer(True)
    assert ag.last_steps[1]["check"].startswith("\u2717 The box holds"), ag.last_steps
    print("ok  D48: each action's effect is checked in code (the box's value, the page) and reported")


def test_d48_the_trajectory_harness_scores_whole_tasks():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import eval_trajectory as ev
    scs = {s["name"]: s for s in ev.load()}
    # reading order of the YouTube home: [1] Close window, [2] Search box, [3] Search button, [4] Home...
    llm = Script(call("plan", steps=["type it", "search"]), call("type_text", id=2, name="Search", text="carryminati"),
                 call("submit", id=2, name="Search"), call("done", summary="Searched."))
    r = ev.run(scs["search_youtube"], llm)
    assert r["ok"] and r["calls"] == 4 and r["did"][-1] == ("submit", "Search", ""), r
    bad = ev.run(scs["minimize_vscode"], Script(call("close_app", name="VS Code")))
    assert not bad["ok"], "closing is never minimizing"
    good = ev.run(scs["minimize_vscode"], Script(call("window_state", name="VS Code", state="minimize")))
    assert good["ok"], good
    cur = ev.run(scs["privacy_curtain"], Script(call("curtain", on=True)))
    assert cur["ok"], cur
    print("ok  D48: the trajectory eval runs whole tasks on invented screens and scores them")


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
