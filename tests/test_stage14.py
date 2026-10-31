"""One runnable check for D54–D57 (docs/PLAN-2026-10-31.md): Gemini as a provider with a
backup that can't run out, asking only when unsure, Intelligent UI templates, step playback.
`python tests/test_stage14.py`. No network: every endpoint is an httpx.MockTransport."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jimmy.config as jc  # noqa: E402
from jimmy import llm as jllm  # noqa: E402
from jimmy.llm import LLM, LLMError  # noqa: E402

GEMINI_URL, _ = jc.ENDPOINTS["gemini"]
NVIDIA_URL, _ = jc.ENDPOINTS["nvidia"]
jc.RETRY_WAIT_S = 0


def _ok(text="ok"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def _sse(*pieces):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
    return httpx.Response(200, text="\n\n".join(lines + ["data: [DONE]"]) + "\n\n",
                          headers={"content-type": "text/event-stream"})


def _pair(gemini_handler, nvidia_handler):
    """A Gemini client with an NVIDIA backup, both on mock transports."""
    g = LLM(key="g", model="gemini-3.8-flash", base_url=GEMINI_URL, transport=httpx.MockTransport(gemini_handler))
    b = LLM(key="n", model=jc.NVIDIA_MODEL, base_url=NVIDIA_URL, transport=httpx.MockTransport(nvidia_handler))
    b.tools_model = jc.NVIDIA_TOOLS_MODEL
    g.backup = b
    return g, b


def test_d54_gemini_request_shape():
    seen = []

    def h(req):
        seen.append(json.loads(req.content))
        return _ok()
    g = LLM(key="g", model="gemini-3.8-flash", base_url=GEMINI_URL, transport=httpx.MockTransport(h))
    assert g.gemini and g.chat([{"role": "user", "content": "hi"}], max_tokens=100) == "ok"
    g.chat([{"role": "user", "content": "hi"}], max_tokens=100, thinking=True)
    plain, think = seen
    assert plain["reasoning_effort"] == "low" and think["reasoning_effort"] == "medium"
    assert "temperature" not in plain and "chat_template_kwargs" not in plain, "Gemini 3 sets its own"
    assert plain["max_tokens"] == 100 + jc.GEMINI_THINK_ROOM, "room for thinking"
    print("ok  D54: Gemini's request: low thinking (medium when asked), its own temperature, room to think")


def test_d54_thought_signatures_kept_and_stood_in():
    sig = {"google": {"thought_signature": "abc"}}
    msgs = [{"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "click", "arguments": "{}"}, "extra_content": sig}]},
            {"role": "tool", "tool_call_id": "1", "content": "Done"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "2", "type": "function", "function": {"name": "click", "arguments": "{}"}}]}]
    g = LLM(key="g", model="gemini-3.8-flash", base_url=GEMINI_URL)
    out = g._wire(msgs)
    assert out[1]["tool_calls"][0]["extra_content"] == sig, "Gemini's own signature, unchanged"
    assert out[3]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == jllm.DUMMY_SIGNATURE
    n = LLM(key="n", model=jc.NVIDIA_MODEL, base_url=NVIDIA_URL)
    assert all("extra_content" not in c for m in n._wire(msgs) for c in m.get("tool_calls") or [])
    assert "extra_content" in msgs[1]["tool_calls"][0], "the agent's own history is never changed"
    print("ok  D54: thought signatures go back unchanged; a call Gemini didn't make gets the stand-in")


def test_d54_backup_on_a_daily_quota_then_stays():
    calls = {"g": 0, "n": 0}

    def gem(req):
        calls["g"] += 1
        return httpx.Response(429, json={"error": {"message": "Quota exceeded for GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})

    def nv(req):
        calls["n"] += 1
        return _ok("from nvidia")
    g, _ = _pair(gem, nv)
    assert g.chat([{"role": "user", "content": "hi"}]) == "from nvidia"
    left = g._down_until - time.time()
    assert 0 < left <= 86_400 and abs(left - jllm._pacific_midnight_in()) < 5, "until midnight Pacific"
    tried = calls["g"]
    assert g.chat([{"role": "user", "content": "again"}]) == "from nvidia" and calls["g"] == tried, \
        "while it's down, Gemini isn't asked at all"
    print("ok  D54: a daily quota sends calls to NVIDIA in the same call, until midnight Pacific")


def test_d54_backup_on_outage_tools_and_streams():
    def down(req):
        return httpx.Response(503, json={"error": "overloaded"})

    def nv(req):
        body = json.loads(req.content)
        if body.get("stream"):
            return _sse("from ", "nvidia")
        if body.get("tools"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "t", "type": "function", "function": {"name": "reply", "arguments": "{}"}}]}}]})
        return _ok("nv")
    g, b = _pair(down, nv)
    msg = g.chat_tools([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert msg["tool_calls"][0]["function"]["name"] == "reply"
    assert 0 < g._down_until - time.time() <= jc.BACKUP_RETRY_S + 1, "an outage: a minute, then try again"
    g._down_until = 0
    assert "".join(g.chat_stream([{"role": "user", "content": "x"}])) == "from nvidia", "a stream before its first word"

    def half(req):
        return _sse("Hel")
    g2, _ = _pair(half, nv)
    real = g2._stream

    def breaks(body):
        yield "Hel"
        raise LLMError("LLM stream broke: ReadError", None)
    g2._stream = breaks
    got = []
    try:
        for p in g2.chat_stream([{"role": "user", "content": "x"}]):
            got.append(p)
    except LLMError:
        pass
    else:
        raise AssertionError("a stream that has spoken must not switch mid-sentence")
    g2._stream = real
    assert got == ["Hel"]
    assert g.tool_fallbacks()[0] == "backup:" + jc.NVIDIA_TOOLS_MODEL, "a slow Gemini step also asks NVIDIA"
    print("ok  D54: an outage moves tool steps and streams to NVIDIA; never mid-sentence; slow steps ask it too")


def test_d54_models_go_to_their_own_provider():
    assert jllm.endpoint_for("gemini-3.8-flash") == "gemini"
    assert jllm.endpoint_for("gpt-6-luna") == "openai"
    assert jllm.endpoint_for("meta/llama-3.2-11b-vision-instruct") == "nvidia"
    g = LLM(key="g", model="gemini-3.8-flash", base_url=GEMINI_URL)
    v = jllm.for_model("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", like=g, attempts=1)
    assert v.base_url == NVIDIA_URL.rstrip("/") and v.key != "g", "a screenshot never rides Gemini's key"
    same = jllm.for_model("gemini-3.8-flash", like=g)
    assert same.key == "g" and same.base_url == g.base_url
    print("ok  D54: each model goes to its own provider and key (screenshots to NVIDIA while Gemini talks)")


def test_d54_provider_switch_and_screenshot_choice():
    code = ("from jimmy import config as c; from jimmy.llm import LLM; l = LLM(); "
            "print(c.API_KEY_ENV, c.MODEL, c.TOOLS_MODEL, c.VISION_MODELS[0], bool(l.backup), l.configured)")
    env = {**os.environ, "JIMMY_PROVIDER": "gemini", "GEMINI_API_KEY": "test-g", "NVIDIA_API_KEY": "test-n"}
    env.pop("JIMMY_GEMINI_SCREENSHOTS", None)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env).stdout.split()
    assert out == ["GEMINI_API_KEY", "gemini-3.8-flash", "gemini-3.8-flash",
                   "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "True", "True"], out
    env["JIMMY_GEMINI_SCREENSHOTS"] = "1"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env).stdout.split()
    assert out[3] == "gemini-3.8-flash", "screenshots to Gemini only when the human says so"
    env.pop("GEMINI_API_KEY")
    env["GOOGLE_API_KEY"] = "test-g2"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), env=env).stdout.split()
    assert out[-1] == "True", "GOOGLE_API_KEY works too"
    print("ok  D54: JIMMY_PROVIDER=gemini: Gemini talks and picks tools, NVIDIA backs it up and sees screenshots")


def test_d54_pacific_midnight():
    import calendar
    eight_utc = calendar.timegm((2026, 10, 26, 8, 0, 0))        # 08:00 UTC: midnight in UTC-8
    assert jllm._pacific_midnight_in(eight_utc) == 86_400
    assert jllm._pacific_midnight_in(eight_utc - 60) == 60
    print("ok  D54: a daily quota is back at midnight Pacific (UTC-8, never early)")


# --- D55: ask only when unsure; D57: steps played back --------------------------------------
import types  # noqa: E402

import ambient.agent as agent_mod  # noqa: E402
from ambient import act, policy  # noqa: E402
from ambient import config as acfg  # noqa: E402
from ambient.agent import Agent  # noqa: E402

T = act.Target
agent_mod.time = types.SimpleNamespace(sleep=lambda s: None, monotonic=time.monotonic)
acfg.AUTO_GRACE_S = acfg.STEP_SHOW_S = 0


def call(tool: str, /, **args) -> dict:
    return {"tool_calls": [{"id": f"c{tool}", "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(args)}}], "content": ""}


class Script:
    configured = True

    def __init__(self, *steps):
        self.steps = list(steps)

    def chat_tools(self, messages, tools, **kw):
        return self.steps.pop(0) if self.steps else {"content": "Done.", "tool_calls": []}


BOX = T("Search", "EditControl", (100, 100, 400, 130), frozenset({"value"}), hwnd=1)
SCREEN = [T("Close window", "ButtonControl", (960, 0, 1000, 20), frozenset({"invoke"}), hwnd=1), BOX,
          T("Images", "HyperlinkControl", (100, 160, 160, 180), frozenset({"invoke"}), hwnd=1),
          T("Videos", "HyperlinkControl", (170, 160, 230, 180), frozenset({"invoke"}), hwnd=1),
          T("Delete history", "ButtonControl", (300, 160, 400, 180), frozenset({"invoke"}), hwnd=1)]


def env(did: list, screen=SCREEN):
    # After Enter, the title changes like a results page loading (the D48 check reads it).
    title = lambda: "cats - Google Search" if any(d[0] == "submit" for d in did) else "Google"  # noqa: E731
    return {"window": lambda: ("Chrome", title(), (0, 0, 1000, 600)), "controls": lambda: list(screen),
            "status": lambda: "Jimmy, live.", "wiki_index": lambda: "(empty)", "wiki": lambda p: "",
            "lists": lambda: "", "conversation": lambda: "", "look": lambda q, t: "a picture",
            "search": lambda q: "", "open_app": lambda n: f"Opening {n}.", "close_app": lambda n: f"Closed {n}.",
            "open_url": lambda u: f"Opened {u}.", "cursor": lambda t, a: did.append(("cursor", a, t.name)),
            "perform": lambda t, text: did.append(("perform", t.name, text)) or f"Done: {t.name}.",
            "submit": lambda t: did.append(("submit", t.name)) or f"Searched in {t.name}.",
            "window_state": lambda n, s: did.append(("window_state", n, s)) or f"{s} {n}.",
            "progress": lambda s: did.append(("progress", s)), "doing": lambda s: did.append(("doing", s)),
            "steps": lambda d: did.append(("steps", d["state"], tuple(d["status"])))}


def _task(question, screen=SCREEN):
    return types.SimpleNamespace(question=question, answers=[], targets=list(screen))


def test_d55_sure_means_named_unique_and_reversible():
    images = SCREEN[2]
    assert policy.sure("click", {}, images, _task("click on images"))[0], "named, nothing else like it"
    assert not policy.sure("click", {}, images, _task("click the first link"))[0], "not named: not sure"
    two = [T("Search", "EditControl", (0, 0, 9, 9), frozenset({"value"})),
           T("Search", "ButtonControl", (20, 0, 29, 9), frozenset({"invoke"}))]
    ok, cands = policy.sure("click", {}, two[1], _task("click search", two))
    assert not ok and len(cands) == 2, "two controls called Search: ask which"
    assert policy.sure("type_text", {}, BOX, _task("search for cats"))[0], "the one search box"
    msg = T("Message", "EditControl", (0, 0, 9, 9), frozenset({"value"}))
    assert not policy.sure("type_text", {}, msg, _task("type hello in message", [msg]))[0], "a chat box: asks"
    assert not policy.sure("submit", {}, msg, _task("send it", [msg]))[0], "Enter in a chat box sends: asks"
    assert policy.sure("window_state", {"name": "VS Code", "state": "minimize"}, None, _task("minimize vs code"))[0]
    assert not policy.sure("window_state", {"name": "Spotify", "state": "minimize"}, None, _task("minimize it"))[0]
    assert policy.fit("click on carry minati", T("CarryMinati", "HyperlinkControl", (0, 0, 9, 9), frozenset())) == 1.0
    print("ok  D55: sure = the user named this control, no other fits as well, and it can be undone")


def test_d55_a_sure_action_runs_without_a_yes():
    acfg.AUTONOMY = "when_unsure"
    did = []
    out = Agent(Script(call("click", id=3, name="Images")), env(did)).start("click on images")
    assert out.kind == "done" and ("perform", "Images", None) in did, out
    assert any(d[0] == "doing" and "Images" in d[1] and "stop" in d[1] for d in did), "said first, with a way to stop"
    did = []
    out = Agent(Script(call("click", id=5, name="Delete history")), env(did)).start("click delete history")
    assert out.kind == "await" and "Say yes" in out.say and not any(d[0] == "perform" for d in did), "risky: asks"
    acfg.AUTONOMY = "always"
    did = []
    out = Agent(Script(call("click", id=3, name="Images")), env(did)).start("click on images")
    assert out.kind == "await" and not any(d[0] == "perform" for d in did), "'always': every action asks"
    acfg.AUTONOMY = "when_unsure"
    print("ok  D55: a sure, reversible action is shown, then done; risky ones and 'always' still ask")


def test_d55_stop_in_the_grace_window():
    did = []
    ag = Agent(Script(call("click", id=3, name="Images")), {})
    e = env(did)
    e["doing"] = lambda s: setattr(ag, "cancelled", True)       # "stop", said while it's shown
    ag.env = e
    out = ag.start("click on images")
    assert not any(d[0] == "perform" for d in did) and out.data.get("cancelled"), out
    print("ok  D55: 'stop' while it's shown, and nothing is done")


def test_d55_unsure_asks_which_one_by_voice_or_button():
    two = [T("Search", "EditControl", (0, 0, 90, 20), frozenset({"value"}), hwnd=1),
           T("Search", "ButtonControl", (100, 0, 140, 20), frozenset({"invoke"}), hwnd=1)]
    for answer, want in (("the second one", "ButtonControl"), ("search button", "ButtonControl"),
                         ("yes", "EditControl")):
        did = []
        ag = Agent(Script(call("click", id=2, name="Search")), env(did, two))
        out = ag.start("click search")
        assert out.kind == "await" and out.data["choices"] == ["Search (box)", "Search (button)"], out
        assert ag.waiting_for_answer(), "the reply goes to the agent, not to 'nothing to confirm'"
        done = ag.answer(None, answer)
        assert done.kind == "done" and ("perform", "Search", None) in did, (answer, done)
    ag = Agent(Script(call("click", id=2, name="Search")), env([], two))
    ag.start("click search")
    assert ag.answer(None, "neither").data.get("cancelled")
    print("ok  D55: not sure which: 'Search (box) or Search (button)?'; an ordinal, a name or yes picks one")


def test_d55_d57_a_safe_plan_starts_and_is_played_back():
    did = []
    plan = call("plan", steps=["type carryminati in the search box", "press Enter"])
    ag = Agent(Script(plan, call("type_text", id=2, name="Search", text="carryminati"),
                      call("submit", id=2, name="Search"), call("done", summary="Searched.")), env(did))
    out = ag.start("search for carryminati")
    assert out.kind == "done" and out.say == "Searched.", out
    assert ("perform", "Search", "carryminati") in did and ("submit", "Search") in did, did
    steps = [d for d in did if d[0] == "steps"]
    assert steps[0][1] == "running" and steps[0][2][0] == "running", steps[0]
    assert steps[-1][1] == "done" and set(steps[-1][2]) == {"done"}, steps[-1]
    did = []
    plan = call("plan", steps=["type hi in the message box", "send the message"])
    out = Agent(Script(plan), env(did)).start("send hi to sam")
    assert out.kind == "await" and "Here's the plan" in out.say, "a plan that sends: its own yes"
    assert [d for d in did if d[0] == "steps"][0][1] == "proposed"
    print("ok  D55/D57: a plan with nothing risky starts on its own, live on its card; one that sends asks")


def test_d55_an_auto_plan_asks_at_its_first_unsure_step():
    did = []
    plan = call("plan", steps=["open a result"])
    ag = Agent(Script(plan, call("click", id=3, name="Images")), env(did))
    out = ag.start("open a result for me")
    assert out.kind == "await" and not any(d[0] == "perform" for d in did), "'a result': not named, so it asks"
    print("ok  D55: a plan that started on its own still asks at an action it isn't sure of")


# --- D56: Intelligent UI through the Asker ---------------------------------------------------
from datetime import datetime  # noqa: E402

import ambient.ask as ask_mod  # noqa: E402
from ambient import ui  # noqa: E402
from ambient.db import Store  # noqa: E402

NOW = int(datetime(2026, 10, 31, 21, 0).timestamp() * 1000)
real_now = ask_mod.now_ms


class FakeJimmy:
    def __init__(self, *steps):
        self.llm = Script(*steps)

    def ask_stream(self, q, session, snippets, instructions, **kw):
        yield "An answer."


def _asker(*steps, screen=SCREEN):
    events, spoken = [], []
    ask_mod.now_ms = lambda: NOW
    did = []
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=FakeJimmy(*steps),
                      actions={"state": lambda: {}, "trace": lambda t: None, "agent_controls": lambda: list(screen),
                               "agent_window": lambda: ("Chrome", "Google", (0, 0, 1000, 600)),
                               "perform_target": lambda t, text: did.append(("perform", t.name, text)) or f"Done: {t.name}.",
                               "submit_target": lambda t: did.append(("submit", t.name)) or f"Searched in {t.name}.",
                               "show_cursor": lambda t, a: None})

    def say(text):
        events.clear()
        a.hear(NOW, "mic", text, NOW - 1500)
        assert a.wait_idle(10), text
        return list(events)
    return a, say, spoken, did


def _cards(events):
    return [e["ui"] for e in events if e["type"] == "answer_ui"]


def test_d56_cards_through_the_asker():
    try:
        two = [T("Search", "EditControl", (0, 0, 90, 20), frozenset({"value"}), hwnd=1),
               T("Search", "ButtonControl", (100, 0, 140, 20), frozenset({"invoke"}), hwnd=1)]
        a, say, spoken, did = _asker(call("click", id=2, name="Search"), screen=two)
        ev = say("Jimmy, click search")
        card = _cards(ev)[-1]
        assert card["template"] == "choice" and card["data"]["options"] == ["Search (box)", "Search (button)"], card
        start = [e for e in ev if e["type"] == "answer_start"][-1]
        assert start["mode"] == "ask", "Jimmy's question: not D28's 'screen or earlier?' buttons"
        say("Search (button)")                                  # a tap sends the label, like saying it
        assert ("perform", "Search", None) in did, did

        a, say, spoken, did = _asker(call("click", id=5, name="Delete history"))
        card = _cards(say("Jimmy, click delete history"))[-1]
        assert card["template"] == "confirm" and card["data"]["yes"] == "Do it", card

        table = {"template": "table", "data": {"columns": ["Train", "Leaves"], "rows": [["Deccan Queen", "17:10"]]}}
        a, say, spoken, did = _asker(call("reply", text="The Deccan Queen leaves at 17:10.", ui=table))
        card = _cards(say("Jimmy, which train leaves first"))[-1]
        assert card["template"] == "table" and spoken[-1] == "The Deccan Queen leaves at 17:10.", (card, spoken)
        bad = {"template": "steps", "data": {"steps": ["rm -rf"]}}
        a, say, spoken, did = _asker(call("reply", text="Okay.", ui=bad))
        assert not _cards(say("Jimmy, hello there friend")), "the model can't use code's templates"

        plan = call("plan", steps=["type carryminati in the search box", "press Enter"])
        a, say, spoken, did = _asker(plan, call("type_text", id=2, name="Search", text="carryminati"),
                                     call("submit", id=2, name="Search"), call("done", summary="Searched."))
        ev = say("Jimmy, type carryminati in the search box and press enter")   # ("search for X" is the timeline's)
        live = [e["ui"]["data"]["state"] for e in ev if e["type"] == "steps"]
        assert live[0] == "running" and live[-1] == "done", live
        assert _cards(ev)[-1]["data"]["state"] == "done", "the answer carries the finished plan"
        assert spoken[-1] == "Searched." and ("submit", "Search") in did
    finally:
        ask_mod.now_ms = real_now
    print("ok  D56: 'which one?' as buttons, a yes/no as two, the model's table, a plan live then finished")


def test_d56_validation_is_the_trust_boundary():
    assert ui.validate({"template": "steps", "data": {"steps": ["x"]}}, model=True) is None
    assert ui.validate({"template": "html", "data": {}}) is None
    t = ui.validate({"template": "table", "data": {"columns": ["a", "b"], "rows": [["<script>", "2", "3"]] * 20}},
                    model=True)
    assert len(t["data"]["rows"]) == 8 and t["data"]["rows"][0] == ["<script>", "2"], "capped; text stays text"
    assert ui.validate({"template": "chart", "data": {"bars": [{"label": "a", "value": -1}, {"label": "b", "value": 1}]}},
                       model=True) is None, "a chart needs two real bars"
    assert ui.choice("Which?", ["one"]) is None, "a choice needs two options"
    print("ok  D56: only known templates, capped sizes, plain strings, real numbers")


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
