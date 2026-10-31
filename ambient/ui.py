"""Intelligent UI (D56): an answer can carry one card built from a fixed template.

The idea is OpenAI's (GPT-6's "Intelligent UI", 2026-10-07): answer with text, visuals and
interactive pieces when they help, plain text when that's best. Jimmy's version is a
registry of fixed templates (overlay/src/Templates.jsx), never model-written markup:

- code fills steps, choice, confirm and list (lines about Jimmy's own actions are written
  by code, as invariant 9 has it for cards);
- the model may fill table, checklist and chart, through `reply`'s `ui` argument, only
  when plain text would be worse.

Everything passes `validate` before it's published: a known template, sizes capped,
every string cut short and shown as text by React (captured text is untrusted,
invariant 8), numbers checked. OpenAI's own rules for in-chat UI: at most two actions on
a card, no scrolling inside a card, nothing long or sensitive in it.
"""
from __future__ import annotations

import math

TEMPLATES = ("steps", "choice", "confirm", "list", "table", "checklist", "chart")
MODEL_TEMPLATES = ("table", "checklist", "chart")       # what `reply`'s ui may use
MAX_TEXT = 80
STEP_STATES = ("pending", "running", "done", "failed", "skipped")


def _s(x, n: int = MAX_TEXT) -> str:
    t = " ".join(str(x if x is not None else "").split())
    return t if len(t) <= n else t[:n - 1] + "…"


def _strings(xs, most: int, n: int = MAX_TEXT) -> list[str]:
    return [_s(x, n) for x in (xs if isinstance(xs, list) else [])[:most] if _s(x, n)]


def validate(ui, model: bool = False) -> dict | None:
    """The card to publish, or None. `model`: it came from the model (only its templates)."""
    if not isinstance(ui, dict):
        return None
    kind, d = ui.get("template"), ui.get("data") if isinstance(ui.get("data"), dict) else {}
    if kind not in (MODEL_TEMPLATES if model else TEMPLATES):
        return None
    title = _s(d.get("title"), 60)
    if kind == "steps":
        steps = _strings(d.get("steps"), 8, 90)
        status = [s if s in STEP_STATES else "pending" for s in (d.get("status") or [])][:len(steps)]
        status += ["pending"] * (len(steps) - len(status))
        state = d.get("state") if d.get("state") in ("proposed", "running", "done", "failed", "stopped") else "running"
        return {"template": kind, "data": {"title": title, "steps": steps, "status": status, "state": state,
                                           "auto": bool(d.get("auto"))}} if steps else None
    if kind == "choice":
        options = _strings(d.get("options"), 4, 60)
        return {"template": kind, "data": {"question": _s(d.get("question"), 120), "options": options}} \
            if len(options) >= 2 else None
    if kind == "confirm":
        what = _s(d.get("what"), 120)
        return {"template": kind, "data": {"what": what, "why": _s(d.get("why"), 120),
                                           "yes": _s(d.get("yes") or "Do it", 20),
                                           "no": _s(d.get("no") or "Cancel", 20)}} if what else None
    if kind == "list":
        items = [{"text": _s(i.get("text")), "note": _s(i.get("note"), 40)}
                 for i in (d.get("items") if isinstance(d.get("items"), list) else [])[:8]
                 if isinstance(i, dict) and _s(i.get("text"))]
        return {"template": kind, "data": {"title": title, "items": items,
                                           "more": max(0, int(d.get("more") or 0))}} if items else None
    if kind == "table":
        cols = _strings(d.get("columns"), 5, 24)
        rows = [[_s(c, 40) for c in (r if isinstance(r, list) else [])[:len(cols)]]
                for r in (d.get("rows") if isinstance(d.get("rows"), list) else [])[:8]]
        rows = [r + [""] * (len(cols) - len(r)) for r in rows if any(r)]
        return {"template": kind, "data": {"title": title, "columns": cols, "rows": rows}} \
            if len(cols) >= 2 and rows else None
    if kind == "checklist":
        items = _strings(d.get("items"), 8, 90)
        return {"template": kind, "data": {"title": title, "items": items}} if len(items) >= 2 else None
    if kind == "chart":
        bars = []
        for b in (d.get("bars") if isinstance(d.get("bars"), list) else [])[:8]:
            try:
                v = float(b.get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            if math.isfinite(v) and v >= 0 and _s(b.get("label"), 30):
                bars.append({"label": _s(b.get("label"), 30), "value": v})
        return {"template": kind, "data": {"title": title, "unit": _s(d.get("unit"), 12), "bars": bars}} \
            if len(bars) >= 2 else None
    return None


# --- what code fills ------------------------------------------------------------------------
def steps(d: dict) -> dict | None:
    """The agent's plan, live (D57): from Agent._show_steps."""
    return validate({"template": "steps", "data": d})


def choice(question: str, options: list[str]) -> dict | None:
    return validate({"template": "choice", "data": {"question": question, "options": options}})


def confirm(what: str, why: str = "") -> dict | None:
    return validate({"template": "confirm", "data": {"what": what, "why": why}})


def items(title: str, rows: list[tuple[str, str]], more: int = 0) -> dict | None:
    return validate({"template": "list", "data": {"title": title, "more": more,
                                                  "items": [{"text": a, "note": b} for a, b in rows]}})


# The model's side: the `ui` argument of `reply` (agent.py), described here so the
# description and the validator can't drift apart.
REPLY_UI = {
    "type": "object",
    "description": ("Optional, rarely: a card beside your words, only when plain text would be worse. "
                    "table: {columns:[...], rows:[[...]]} to compare a few things; checklist: {items:[...]} "
                    "for steps the user follows themselves; chart: {unit, bars:[{label, value}]} for "
                    "numbers worth seeing. Keep `text` short: it's what is said aloud."),
    "properties": {"template": {"type": "string", "enum": list(MODEL_TEMPLATES)},
                   "data": {"type": "object"}},
    "required": ["template", "data"],
}


if __name__ == "__main__":
    assert validate({"template": "script", "data": {}}) is None
    assert validate({"template": "steps", "data": {"steps": ["a"]}}, model=True) is None, "steps: code only"
    t = validate({"template": "table", "data": {"columns": ["a", "b"], "rows": [["1", "2", "3"]]}}, model=True)
    assert t and t["data"]["rows"] == [["1", "2"]]
    c = validate({"template": "chart", "data": {"bars": [{"label": "x", "value": "nan"}, {"label": "y", "value": 2},
                                                        {"label": "z", "value": 3}]}}, model=True)
    assert c and [b["label"] for b in c["data"]["bars"]] == ["y", "z"]
    assert len(validate({"template": "checklist", "data": {"items": ["x" * 500, "y"]}}, model=True)["data"]["items"][0]) == 90
    print("ui.py self-check ok")
