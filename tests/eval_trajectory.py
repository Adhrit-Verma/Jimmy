"""Whole tasks, not first steps (D48, A9). `python tests/eval_trajectory.py [--only NAME]`.
Live: needs the key (NVIDIA_API_KEY, or OPENAI_API_KEY with JIMMY_PROVIDER=openai).

Each frozen scenario in tests/eval/trajectories.json is an invented world: screens that
change when an action hits a control. The real agent runs on it, every proposal is
approved as the user would ("yes"), and the run is scored: success, steps, model calls,
prompt tokens, seconds. Run it before and after any change to SYSTEM, the tools or the
loop; tests/test_stage13.py checks the harness itself with a scripted model."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0]))

from ambient import act  # noqa: E402

KIND = {"button": "ButtonControl", "link": "HyperlinkControl", "edit": "EditControl", "tab": "TabItemControl",
        "checkbox": "CheckBoxControl"}
CAN = {"edit": frozenset({"value"}), "checkbox": frozenset({"toggle"}), "tab": frozenset({"select"})}


def load(path: Path | None = None) -> list[dict]:
    return json.loads((path or HERE / "eval" / "trajectories.json").read_text(encoding="utf-8"))["scenarios"]


class World:
    """One scenario's screens, and a record of what the agent did to them."""

    def __init__(self, sc: dict):
        self.sc, self.screen, self.did, self.values = sc, sc["start"], [], {}

    def targets(self) -> list:
        s = self.sc["screens"][self.screen]
        return [act.Target(n, KIND[k], (int(x * 19.2), int(y * 10.8), int(x * 19.2) + 60, int(y * 10.8) + 24),
                           CAN.get(k, frozenset({"invoke"})), hwnd=1) for k, n, x, y in s["controls"]]

    def window(self):
        s = self.sc["screens"][self.screen]
        return s["app"], s["title"], (0, 0, 1920, 1080)

    def _move(self, tool: str, name: str) -> None:
        for tr in self.sc.get("transitions", []):
            if tr["on"][0] == tool and tr["on"][1] == name:
                self.screen = tr["to"]
                return

    def perform(self, t, text):
        self.did.append(("type_text" if text is not None else "click", t.name, text or ""))
        if text is not None:
            self.values[t.name] = text
        else:
            self._move("click", t.name)
        return f"Typed into “{t.name}”." if text is not None else f"Done: “{t.name}”."

    def submit(self, t):
        self.did.append(("submit", t.name, ""))
        self._move("submit", t.name)
        return f"Searched in “{t.name}”."

    def windows(self):
        self.did.append(("list_windows", "", ""))
        return [tuple(w) for w in self.sc.get("windows", [])]

    def env(self) -> dict:
        return {"window": self.window, "controls": self.targets, "status": lambda: "Jimmy, live.",
                "wiki_index": lambda: "(empty)", "wiki": lambda p: "", "lists": lambda: "",
                "conversation": lambda: "", "look": lambda q, t: "(no picture in the eval)",
                "search": lambda q: "Nothing captured matches.", "open_app": lambda n: f"Opening {n}.",
                "close_app": lambda n: self.did.append(("close_app", n, "")) or f"Closed {n}.",
                "open_url": lambda u: self.did.append(("open_url", u, "")) or f"Opened {u}.",
                "cursor": lambda t, a: None, "perform": self.perform, "submit": self.submit,
                "progress": lambda s: None, "windows": self.windows,
                "open_apps": lambda: [w[0] for w in self.sc.get("windows", [])],
                "focus_window": lambda n: self.did.append(("focus_window", n, "")) or f"Switched to {n}.",
                "window_state": lambda n, s: self.did.append(("window_state", n, s)) or f"{s.capitalize()}d {n}.",
                "value_of": lambda t: self.values.get(t.name),
                "feature": lambda n, a: self.did.append(("jimmy", n, json.dumps(a))) or "Done."}


def judge(sc: dict, did: list[tuple], jimmy: str | None) -> bool:
    ok = sc["success"]
    if "jimmy" in ok:
        return jimmy == ok["jimmy"] or any(d[0] == "jimmy" and d[1] == ok["jimmy"] for d in did)
    if any(d[0] in ok.get("never", []) for d in did):
        return False
    i = 0
    for d in did:
        if i < len(ok["did"]):
            tools, name, text = (list(ok["did"][i]) + ["", ""])[:3]
            if (d[0] in tools.split("|") and (not name or d[1].lower() == name.lower())
                    and (not text or text.lower() in d[2].lower())):
                i += 1
    return i == len(ok["did"])


def run(sc: dict, llm) -> dict:
    """One scenario through the real agent, approving every proposal."""
    from ambient.agent import Agent
    calls = {"n": 0}
    real = llm.chat_tools

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    llm.chat_tools = counted
    w = World(sc)
    ag = Agent(llm, w.env())
    t0, jimmy, steps = time.monotonic(), None, []
    try:
        out = ag.start(sc["request"])
        for _ in range(8):
            steps += [s for s in ag.last_steps if s not in steps]
            if out.kind != "await":
                break
            out = ag.answer(None, sc.get("answer", "yes")) if out.data.get("ask") else ag.answer(True)
        steps += [s for s in ag.last_steps if s not in steps]
        if out.kind == "done" and out.data.get("tool") == "jimmy":
            jimmy = out.data["action"]
        err = ""
    except Exception as exc:
        out, err = None, f"{type(exc).__name__}: {exc}"
    finally:
        llm.chat_tools = real
    return {"name": sc["name"], "ok": not err and judge(sc, w.did, jimmy), "calls": calls["n"],
            "steps": len(steps), "tokens": sum(int(s.get("prompt") or 0) for s in steps),
            "seconds": round(time.monotonic() - t0, 1), "did": w.did, "error": err,
            "said": getattr(out, "say", "")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    from jimmy.llm import LLM
    llm = LLM()
    if not llm.configured:
        print("no key: set NVIDIA_API_KEY (or OPENAI_API_KEY with JIMMY_PROVIDER=openai)")
        return 1
    rows = [run(sc, llm) for sc in load() if not a.only or sc["name"] == a.only]
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:22s} calls={r['calls']} steps={r['steps']} "
              f"tokens={r['tokens']} {r['seconds']}s  {r['error'] or r['did']}")
    ok = sum(r["ok"] for r in rows)
    print(f"\n{ok}/{len(rows)} tasks done; {sum(r['calls'] for r in rows)} model calls, "
          f"{sum(r['tokens'] for r in rows)} prompt tokens, {sum(r['seconds'] for r in rows):.0f} s")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
