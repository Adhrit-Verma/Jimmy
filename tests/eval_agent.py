"""Live eval of Jimmy's understanding on the human's real commands (D42).
`python tests/eval_agent.py [--system d41|agent] [--only N]`. Needs NVIDIA_API_KEY.

Scores the FIRST decision for each frozen case in tests/eval/real_commands.json:
which outcome (tool), and for clicks/typing, which control. Screens are invented
(tests/eval/screens.json). `d41` replays the old system (rules + one tool pick) for
the baseline; `agent` runs ambient/agent.py's first step with the same fake world."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))
sys.stdout.reconfigure(encoding="utf-8")

from ambient import act  # noqa: E402

KIND = {"button": "ButtonControl", "link": "HyperlinkControl", "edit": "EditControl", "tab": "TabItemControl",
        "checkbox": "CheckBoxControl", "text": "TextControl"}
CAN = {"edit": frozenset({"value"}), "checkbox": frozenset({"toggle"}), "tab": frozenset({"select"}),
       "text": frozenset()}
NOW = int(datetime(2026, 10, 3, 1, 40).timestamp() * 1000)
STATE = """reminders:
  #3 "check the railway booking" at 10:00 on Sat
  #4 "call mom" at 18:00
goals:
  #1 "finish the fellowship essay"
memories:
  #7 "I take the 8:15 train on Mondays\""""


def screen_targets(name: str | None) -> list:
    if not name:
        return []
    s = json.loads((HERE / "eval" / "screens.json").read_text(encoding="utf-8"))[name]
    return [act.Target(n, KIND[k], (int(x * 19.2), int(y * 10.8), int(x * 19.2) + 60, int(y * 10.8) + 24),
                       CAN.get(k, frozenset({"invoke"}))) for k, n, x, y in s["controls"]]


# --- the old system, for the baseline ---------------------------------------------
CMD = {"open": "open_view", "reminders": "list_reminders", "unremind": "reminder_delete", "uncurtain": "curtain",
       "enrol": "remember_face", "unenrol": "forget_face", "timers": "list_reminders", "untimer": "cancel_timer",
       "forget": "forget_data", "calibrate": "calibrate_eyes", "notcall": "not_a_call", "type": "type_text",
       "hush": "reply", "yes": "reply", "no": "reply", "eyes": "reply"}
TOOL = {"open": "open_view", "open_page": "open_url", "ask_back": "ask_user", "goto": "open_view",
        "forget": "forget_data", "type": "type_text", "list_goals": "list_goals"}
MODE = {"screen": "answer", "stats": "answer", "recall": "answer", "chat": "answer", "event": "answer",
        "show": "answer", "goto": "open_view", "clarify": "ask_user", "presence": "presence", "draft": "draft"}


def d41(text: str, targets: list) -> tuple[str, str | None]:
    import ambient.ask as ask_mod
    from ambient.ask import _json_obj, command, nav, route, tool_messages
    from jimmy.llm import LLM
    ask_mod.now_ms = lambda: NOW
    mode, _ = route(text, now=NOW)
    if mode == "command":
        kind, arg = command(text)
        if kind in ("click", "type"):
            m = ask_mod._CMD_RX["type"].match(text) if kind == "type" else None
            t = act.best(targets, m[2] if m else arg, typing=kind == "type")
            return CMD.get(kind, kind), t.name if t else None
        return CMD.get(kind, kind), None
    if mode == "nav":
        a = nav(text)["action"]
        return {"close": "close", "step": "step", "edge": "step", "day": "open_view"}.get(a, a), None
    if mode not in ("chat", "recall"):
        return MODE.get(mode, mode), None
    got = _json_obj(LLM().chat(tool_messages(text, STATE), max_tokens=200, temperature=0.0)) or {}
    tool, args = got.get("tool", "?"), got.get("args") or {}
    if tool in ("click", "type"):
        t = act.best(targets, str(args.get("target") or ""), typing=tool == "type")
        return TOOL.get(tool, tool), t.name if t else None
    return TOOL.get(tool, tool), None


_LLM = None


def agent(text: str, targets: list, screen: str | None) -> tuple[str, str | None]:
    """The real pipeline (D42 decision 4): the instant rules first, the agent for the rest."""
    import ambient.ask as ask_mod
    from ambient.agent import first_decision
    from ambient.ask import command, nav, route, to_agent
    ask_mod.now_ms = lambda: NOW
    mode, _ = route(text, now=NOW)
    if not to_agent(mode, text):
        if mode == "command":
            kind, arg = command(text)
            return ("ask_user" if kind == "click" and not arg else CMD.get(kind, kind)), None
        if mode == "nav":
            a = nav(text)["action"]
            return {"close": "close", "step": "step", "edge": "step", "day": "open_view"}.get(a, a), None
        return MODE.get(mode, mode), None
    time.sleep(0.4)                  # the endpoint rate-limits bursts (429 on 3 of 130)
    global _LLM
    from jimmy.llm import LLM
    _LLM = _LLM or LLM()
    return first_decision(text, targets, screen, STATE, _LLM, now=NOW)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="agent", choices=["d41", "agent"])
    ap.add_argument("--only", type=int, default=0)
    a = ap.parse_args()
    cases = json.loads((HERE / "eval" / "real_commands.json").read_text(encoding="utf-8"))["cases"]
    cases = cases[:a.only] if a.only else cases
    right = tool_right = 0
    times = []
    for c in cases:
        targets = screen_targets(c.get("screen"))
        t0 = time.time()
        try:
            out, target = d41(c["said"], targets) if a.system == "d41" else agent(c["said"], targets, c.get("screen"))
        except Exception as exc:
            out, target = f"error {type(exc).__name__}: {str(exc)[:60]}", None
        times.append(time.time() - t0)
        tool_ok = out in c["ok"]
        aim_ok = out not in ("click", "type_text", "submit") or not c.get("target") or \
            bool(target and c["target"].lower() in target.lower())
        tool_right += tool_ok
        right += tool_ok and aim_ok
        mark = "ok  " if tool_ok and aim_ok else "AIM " if tool_ok else "MISS"
        print(f"{mark} {times[-1]:4.1f}s  {c['said'][:46]!r:50s} -> {out}{f' [{target}]' if target else ''}"
              f"{'' if tool_ok else f'   want {c[chr(111) + chr(107)]}'}")
    times.sort()
    print(f"\n{a.system}: {right}/{len(cases)} right ({tool_right} right tool); "
          f"median {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
