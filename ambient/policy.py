"""What the agent may do, decided in code (D49, A6).

Every screen action the model proposes passes through `check()` before anything is
shown or done. The model reads screen text, and screen text is untrusted (invariant 8);
research on prompt injection (CaMeL, plan-then-execute) finds that rules in the prompt
fail against a determined page, and only a layer outside the model holds. So this layer
decides, the same way whichever model runs:

- refuse: never done (a password box, words the user didn't say, a control that isn't
  there or has changed, a control the user just said no to);
- stop: the task ends with a line (a CAPTCHA: the user ticks it);
- ask: always its own yes, even inside an approved plan (anything that can't be undone,
  a site the user didn't name, a control whose name reads like an instruction);
- allow: done after the plan's yes, or after its own yes when there's no plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import act, config

# A control whose name tells the agent what to do is a page talking to the model.
INJECTED = re.compile(r"\b(?:ignore (?:the|all|any|previous|prior|your|above)|disregard|instead of (?:the )?user|"
                      r"you are (?:now )?an? (?:ai|assistant|agent)|system prompt|new instructions?|"
                      r"assistant[:,]|do not tell the user|without asking)\b", re.I)


@dataclass
class Verdict:
    kind: str                      # allow | ask | refuse | stop
    target: act.Target | None = None
    say: str = ""                  # refuse: the tool result for the model; stop: the line for the user
    why: str = ""                  # ask: the warning added to the question


def _host_said(url: str, said: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    words = set(re.findall(r"[a-z0-9]+", said.lower()))
    parts = [p for p in host.split(".") if p and p not in ("com", "org", "net", "in", "co", "io", "www")]
    return bool(parts) and any(p in words for p in parts)


def check(name: str, args: dict, task, rejected: list[str], open_apps: list[str] | None = None) -> Verdict:
    """The verdict on one proposed action. `task` is the agent's Task (question, answers,
    targets); `rejected` the controls the user said no to; `open_apps` the window list."""
    from .agent import CAPTCHA, NO_CAPTCHA, RISKY_TOOLS, name_check, name_fits, said_by_user
    target = None
    if name in ("click", "type_text", "submit"):
        try:
            i = int(args.get("id"))
        except (TypeError, ValueError):
            i = 0
        target = task.targets[i - 1] if 1 <= i <= len(task.targets) else None
        if target is None:
            return Verdict("refuse", say="No control has that number. Use a number from <screen>.")
        if not name_fits(str(args.get("name") or ""), target):
            # D45: after a maximize the numbers shifted and "click 4" (Maximize) proposed New Tab.
            return Verdict("refuse", say=f"Control {args.get('id')} is now “{target.name}”, not "
                                         f"“{args.get('name')}”: the screen changed. Use the new numbers.")
        if name == "click":
            target = name_check(task.question, target, task.targets)
        if CAPTCHA.search(target.name):
            return Verdict("stop", target, NO_CAPTCHA)
        if target.name in rejected:
            return Verdict("refuse", target, f"The user said no to “{target.name}” a moment ago: pick "
                                             "another control, or look_at_screen.")
        if target.password and name in ("type_text", "submit"):
            return Verdict("refuse", target, "Never into a password box.")
    if name == "type_text" and not said_by_user(str(args.get("text") or ""), task):
        return Verdict("refuse", target, "Not typing that: words the user didn't say. Ask the user what to type.")
    if name in ("focus_window", "window_state", "close_app") and not str(args.get("name") or "").strip():
        return Verdict("refuse", say="Which app? Give its name.")
    if name == "window_state" and args.get("state") not in ("minimize", "maximize", "restore"):
        return Verdict("refuse", say="state is minimize, maximize or restore.")
    if name == "close_app" and open_apps is not None:
        want = re.sub(r"[^a-z0-9]", "", str(args.get("name")).lower()).replace("google", "")
        have = [re.sub(r"[^a-z0-9]", "", a.lower()).replace("google", "") for a in open_apps]
        if want and have and not any(h and (h == want or h.startswith(want) or want.startswith(h)) for h in have):
            return Verdict("refuse", say=f"{args.get('name')} isn't open (list_windows shows what is).")
    why = ""
    if name == "open_url":
        url = str(args.get("url") or "")
        if not re.match(r"^https?://\S+$", url):
            return Verdict("refuse", say="Only http(s) addresses.")
        if not _host_said(url, " ".join([task.question, *task.answers])):
            why = "You didn't name that site."
    if target is not None and INJECTED.search(target.name):
        why = "Its name reads like an instruction to me, not a button."
    risky = name in RISKY_TOOLS or bool(target and act.RISKY.search(target.name)) or bool(why)
    return Verdict("ask" if risky else "allow", target, why=why)


# --- D55: sure enough to act without a yes ------------------------------------------------
# A box whose Enter runs a search or opens an address, not one that sends a message.
SEARCHY = re.compile(r"\b(?:search|address|url|find|query|look ?up|location|go to|omnibox)\b", re.I)
_KIND_WORDS = {"bar": "EditControl", "box": "EditControl", "field": "EditControl", "button": "ButtonControl",
               "link": "HyperlinkControl", "tab": "TabItemControl", "checkbox": "CheckBoxControl"}


def fit(said: str, t: act.Target) -> float:
    """How much of the control's name the user said (0..1), plus a little for a kind they
    named ("the search *box*"). The reverse of act.score, which asks how much of the
    phrase the name holds: "sure" needs the user to have named *this* control."""
    words = act._words(said)
    have = act._words(t.name)
    if not have:
        return 0.0
    heard, joined = set(words), "".join(words)
    cover = sum(1 for w in have if w in heard) / len(have)
    if cover < 1 and len(have) <= 3 and "".join(have) in joined:     # "carry minati" = "CarryMinati"
        cover = 1.0
    hint = next((k for w, k in _KIND_WORDS.items() if w in heard), None)
    return min(1.0, cover + (0.1 if hint and t.kind == hint else 0.0))


def _said(task) -> str:
    return " ".join([task.question, *getattr(task, "answers", [])])


def sure(name: str, args: dict, target, task) -> tuple[bool, list]:
    """(Jimmy is sure enough to do this without a yes, the controls it might mean when it
    isn't). Only for a verdict of *allow*; never for anything policy.check made ask."""
    said = _said(task)
    if name in ("focus_window", "window_state"):
        app = str(args.get("name") or "")
        named = bool(set(act._words(app)) & set(act._words(said))) or app.lower().replace(" ", "") in said.lower().replace(" ", "")
        return named and (name == "focus_window" or args.get("state") in ("minimize", "maximize", "restore")), []
    if name == "open_url":
        return True, []                                  # policy.check already asks for a site they didn't name
    if target is None or name not in ("click", "type_text", "submit"):
        return False, []
    if name in ("type_text", "submit"):
        boxes = [x for x in task.targets if "value" in x.can and SEARCHY.search(x.name)]
        if not SEARCHY.search(target.name):
            return False, []                             # Enter in a chat box sends; typing there asks
        return len(boxes) == 1 or fit(said, target) >= config.AUTO_MIN_FIT, boxes[:3]
    _MIN, AUTO_MARGIN = config.AUTO_MIN_FIT, config.AUTO_MARGIN
    mine = fit(said, target)
    ranked = sorted(task.targets, key=lambda x: -fit(said, x))   # a box too: "click" on it focuses it (D45)
    close = [x for x in ranked if fit(said, x) >= max(_MIN - AUTO_MARGIN, mine - AUTO_MARGIN)]
    twins = [x for x in close if x is not target and (x.name == target.name or fit(said, x) > mine - AUTO_MARGIN)]
    return mine >= _MIN and not twins, (close or ranked)[:3]
