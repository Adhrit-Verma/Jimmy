"""Jimmy's hands, with a virtual cursor (D41).

"Jimmy, click Sign in" / "type hello into the search box": the window in front is
read through UI Automation for things that can be pressed, ticked, picked, opened
or typed into; the best match by name is shown with a cursor of Jimmy's own (the
overlay draws it); only after your yes is it done, through the control's own
pattern (Invoke, Toggle, Select, Expand, SetValue). Your mouse and keyboard are
never touched and no click event is sent, so nothing lands anywhere else.

Never in excluded windows (banking, password managers, Jimmy itself: the bus
checks), never typing into a password box. Control names are screen content,
so untrusted: they are matched, never followed as instructions, and every
action waits for a yes.
"""
from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path

_FILLER = {"the", "a", "an", "on", "in", "into", "button", "link", "box", "field", "tab", "menu", "option",
           "checkbox", "check", "icon", "item", "that", "this", "please", "called", "named", "says", "labelled",
           "labeled", "one"}
_HINTS = {"button": "ButtonControl", "link": "HyperlinkControl", "box": "EditControl", "field": "EditControl",
          "search": "EditControl", "tab": "TabItemControl", "menu": "MenuItemControl",
          "checkbox": "CheckBoxControl", "check": "CheckBoxControl"}
# Words that mean "can't take it back": the yes is asked with a warning (D41).
RISKY = re.compile(r"\b(?:send|delete|remove|submit|pay|buy|purchase|order|post|publish|confirm|transfer|"
                   r"sign out|log ?out|uninstall|discard|erase|reset|format|close account|close window)\b", re.I)


@dataclass
class Target:
    name: str
    kind: str                      # UIA control type name, e.g. "ButtonControl"
    rect: tuple[int, int, int, int]  # left, top, right, bottom (physical screen pixels)
    can: frozenset                 # patterns: invoke / toggle / select / expand / value
    password: bool = False
    uia_name: str = ""             # D42: the control's own name, to find it again ("Close")
    hwnd: int = 0                  # D42: the window it lives in

    @property
    def center(self) -> tuple[int, int]:
        return (self.rect[0] + self.rect[2]) // 2, (self.rect[1] + self.rect[3]) // 2


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[\w']+", (text or "").lower()) if w not in _FILLER]


def score(phrase: str, t: Target) -> float:
    """How well a spoken name fits a control: words in common, then spelling."""
    want, have = _words(phrase), _words(t.name)
    if not want or not have:
        return 0.0
    overlap = len(set(want) & set(have)) / len(set(want))
    close = difflib.SequenceMatcher(None, " ".join(want), " ".join(have)).ratio()
    s = 0.6 * overlap + 0.4 * close
    hint = next((_HINTS[w] for w in re.findall(r"[a-z]+", phrase.lower()) if w in _HINTS), None)
    if hint and t.kind == hint:
        s += 0.1
    return s


def best(targets: list[Target], phrase: str, typing: bool = False) -> Target | None:
    """The control the phrase names, or None if nothing fits well enough."""
    # Typing needs a box that takes text; pressing needs something other than that.
    pool = [t for t in targets if ("value" in t.can if typing else t.can - {"value"})]
    if typing and not _words(phrase) and len(pool) == 1:
        return pool[0]                       # "type hello": the one box there is
    ranked = sorted(pool, key=lambda t: -score(phrase, t))
    return ranked[0] if ranked and score(phrase, ranked[0]) >= 0.45 else None


def _patterns(ctrl, auto) -> frozenset:
    el, out = ctrl.Element, set()
    for name, prop in (("invoke", "IsInvokePatternAvailableProperty"), ("toggle", "IsTogglePatternAvailableProperty"),
                       ("select", "IsSelectionItemPatternAvailableProperty"),
                       ("expand", "IsExpandCollapsePatternAvailableProperty"),
                       ("value", "IsValuePatternAvailableProperty")):
        try:
            if el.GetCurrentPropertyValue(getattr(auto.PropertyId, prop)):
                out.add(name)
        except Exception:
            pass
    return frozenset(out)


_CAPTION = {"Close", "Minimize", "Maximize", "Restore"}


_PATTERN_PROPS = (("invoke", "IsInvokePatternAvailableProperty"), ("toggle", "IsTogglePatternAvailableProperty"),
                  ("select", "IsSelectionItemPatternAvailableProperty"),
                  ("expand", "IsExpandCollapsePatternAvailableProperty"),
                  ("value", "IsValuePatternAvailableProperty"))


def _caption_name(c, name: str) -> str:
    """D42: "Close" is the window's or a tab's: say which."""
    parent = c.GetParentControl()
    ptype = parent.ControlTypeName if parent else ""
    if ptype == "TitleBarControl":
        return f"{name} window"
    if ptype == "TabItemControl" and parent.Name:
        return f"{name} (tab {parent.Name[:60]})"
    return name


def controls(hwnd: int, limit: int = 600) -> list[Target]:
    """What in this window can be pressed, ticked, picked, opened or typed into.
    D47: one cached UI Automation query (UIA_CACHE); the old walk if that fails."""
    from . import config
    if config.UIA_CACHE:
        try:
            return _controls_cached(hwnd, limit)
        except Exception as exc:
            print(f"[act] cached controls failed ({type(exc).__name__}); the old walk")
    return _controls_walk(hwnd, limit)


def _controls_cached(hwnd: int, limit: int = 600) -> list[Target]:
    """The same as _controls_walk, with every property each control needs fetched in the
    one FindAllBuildCache call (a cache request) instead of ~10 cross-process reads per
    control. UI Automation's own advice for bulk reads."""
    import uiautomation as auto
    from uiautomation.uiautomation import _AutomationClient

    from .screen import wake_accessibility
    out: list[Target] = []
    P = auto.PropertyId
    with auto.UIAutomationInitializerInThread():
        wake_accessibility(hwnd)
        root = auto.ControlFromHandle(hwnd)
        uia = _AutomationClient.instance().IUIAutomation
        conds = [uia.CreatePropertyCondition(getattr(P, prop), True) for _, prop in _PATTERN_PROPS]
        cond = conds[0]
        for c in conds[1:]:
            cond = uia.CreateOrCondition(cond, c)
        cr = uia.CreateCacheRequest()
        for pid in (P.NameProperty, P.ControlTypeProperty, P.BoundingRectangleProperty, P.IsOffscreenProperty,
                    P.IsPasswordProperty, P.HelpTextProperty, *[getattr(P, prop) for _, prop in _PATTERN_PROPS]):
            cr.AddProperty(pid)
        found = root.Element.FindAllBuildCache(4, cond, cr)             # 4: all descendants
        names = getattr(auto, "ControlTypeNames", {})
        for i in range(min(found.Length, limit)):
            try:
                el = found.GetElement(i)
                if el.CachedIsOffscreen:
                    continue
                r = el.CachedBoundingRectangle
                if r.right - r.left <= 2 or r.bottom - r.top <= 2:
                    continue
                kind = names.get(el.CachedControlType, "Control")
                own = name = (el.CachedName or "").strip()
                if not name and kind == "EditControl":
                    name = (el.CachedHelpText or "").strip() or "text box"
                if not name:
                    continue
                if kind == "ButtonControl" and name in _CAPTION:
                    name = _caption_name(auto.Control.CreateControlFromElement(el), name)
                can = frozenset(k for k, prop in _PATTERN_PROPS if el.GetCachedPropertyValue(getattr(P, prop)))
                out.append(Target(name[:120], kind, (r.left, r.top, r.right, r.bottom), can,
                                  bool(el.CachedIsPassword), own, hwnd))
            except Exception:
                continue
    return out


def _controls_walk(hwnd: int, limit: int = 600) -> list[Target]:
    """D41's walk: each property read on its own."""
    import uiautomation as auto
    from uiautomation.uiautomation import _AutomationClient

    from .screen import wake_accessibility
    out: list[Target] = []
    with auto.UIAutomationInitializerInThread():
        wake_accessibility(hwnd)
        root = auto.ControlFromHandle(hwnd)
        uia = _AutomationClient.instance().IUIAutomation
        conds = [uia.CreatePropertyCondition(getattr(auto.PropertyId, p), True) for p in (
            "IsInvokePatternAvailableProperty", "IsTogglePatternAvailableProperty",
            "IsSelectionItemPatternAvailableProperty", "IsExpandCollapsePatternAvailableProperty",
            "IsValuePatternAvailableProperty")]
        cond = conds[0]
        for c in conds[1:]:
            cond = uia.CreateOrCondition(cond, c)
        found = root.Element.FindAll(4, cond)            # 4: all descendants
        for i in range(min(found.Length, limit)):
            try:
                c = auto.Control.CreateControlFromElement(found.GetElement(i))
                if c.IsOffscreen:
                    continue
                r = c.BoundingRectangle
                if r.width() <= 2 or r.height() <= 2:
                    continue
                own = name = (c.Name or "").strip()
                if not name and c.ControlTypeName == "EditControl":
                    name = (c.GetPropertyValue(auto.PropertyId.HelpTextProperty) or "").strip() or "text box"
                if not name:
                    continue
                if c.ControlTypeName == "ButtonControl" and name in _CAPTION:
                    # D42: "Click X" once picked the window's Close (the whole app) for a tab.
                    name = _caption_name(c, name)
                out.append(Target(name[:120], c.ControlTypeName, (r.left, r.top, r.right, r.bottom),
                                  _patterns(c, auto), bool(c.Element.CurrentIsPassword), own, hwnd))
            except Exception:
                continue
    return out


def perform(hwnd: int, t: Target, text: str | None = None) -> str:
    """Do it, after your yes. The control is found again (same name, type, place):
    the window may have changed while you decided. Returns what to say."""
    import uiautomation as auto
    from uiautomation.uiautomation import _AutomationClient
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        uia = _AutomationClient.instance().IUIAutomation
        found = root.Element.FindAll(4, uia.CreatePropertyCondition(auto.PropertyId.NameProperty,
                                                                     t.uia_name or t.name))
        best_c, best_d = None, 1e9
        for i in range(found.Length):
            c = auto.Control.CreateControlFromElement(found.GetElement(i))
            if c.ControlTypeName != t.kind:
                continue
            r = c.BoundingRectangle
            d = abs((r.left + r.right) // 2 - t.center[0]) + abs((r.top + r.bottom) // 2 - t.center[1])
            if d < best_d:
                best_c, best_d = c, d
        if best_c is None:
            return f"“{t.name}” isn't there any more."
        return press(best_c, t.name, text, auto)


def press(c, name: str, text: str | None, auto) -> str:
    """What "click" or "type" means for this control, through its own patterns.
    D45: a text box (Chrome's address bar has Value, not Invoke) is "clicked" by
    putting the cursor in it, through UI Automation: no mouse event."""
    if text is not None:
        if c.Element.CurrentIsPassword:
            return "I never type into password boxes."
        vp = c.GetPattern(auto.PatternId.ValuePattern)
        if not vp or vp.IsReadOnly:
            return f"I can't type into “{name}”."
        vp.SetValue(text)
        return f"Typed into “{name}”."
    for pid, verb in ((auto.PatternId.InvokePattern, "Invoke"), (auto.PatternId.TogglePattern, "Toggle"),
                      (auto.PatternId.SelectionItemPattern, "Select")):
        p = c.GetPattern(pid)
        if p:
            getattr(p, verb)()
            return f"Done: “{name}”."
    p = c.GetPattern(auto.PatternId.ExpandCollapsePattern)
    if p:
        (p.Collapse if p.ExpandCollapseState == 1 else p.Expand)()     # 1: expanded
        return f"Opened “{name}”."
    if c.GetPattern(auto.PatternId.ValuePattern):
        c.SetFocus()
        return f"Focused “{name}”."
    return f"I can't press “{name}” without your mouse."


def value_of(hwnd: int, t: Target) -> str | None:
    """D47: what a box holds now (ValuePattern.Value), to check a typing step. None if
    it can't be read (no such control any more, no Value, a password box)."""
    import uiautomation as auto
    from uiautomation.uiautomation import _AutomationClient
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        uia = _AutomationClient.instance().IUIAutomation
        found = root.Element.FindAll(4, uia.CreatePropertyCondition(auto.PropertyId.NameProperty,
                                                                     t.uia_name or t.name))
        for i in range(found.Length):
            c = auto.Control.CreateControlFromElement(found.GetElement(i))
            if c.ControlTypeName != t.kind or c.Element.CurrentIsPassword:
                continue
            vp = c.GetPattern(auto.PatternId.ValuePattern)
            return str(vp.Value) if vp else None
    return None


def submit(hwnd: int, t: Target) -> str:
    """D42: press Enter in a box (to run what was typed there). The box is focused
    through UI Automation and Enter is sent only if the focus really landed there,
    so the key can't go anywhere else."""
    import uiautomation as auto
    from uiautomation.uiautomation import _AutomationClient
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        uia = _AutomationClient.instance().IUIAutomation
        found = root.Element.FindAll(4, uia.CreatePropertyCondition(auto.PropertyId.NameProperty,
                                                                     t.uia_name or t.name))
        box = next((auto.Control.CreateControlFromElement(found.GetElement(i)) for i in range(found.Length)
                    if auto.Control.CreateControlFromElement(found.GetElement(i)).ControlTypeName == t.kind), None)
        if box is None:
            return f"\u201c{t.name}\u201d isn't there any more."
        box.SetFocus()
        focused = auto.GetFocusedControl()
        if not focused or not auto.ControlsAreSame(focused, box):
            return f"I couldn't put the cursor in \u201c{t.name}\u201d, so I didn't press Enter."
        auto.SendKeys("{Enter}", waitTime=0.05)
        return f"Searched in \u201c{t.name}\u201d."


def close_app(name: str) -> str:
    """D42: close an app's windows the way its own X does (WM_CLOSE): it may ask to
    save. Only after the user's yes (the agent asks)."""
    import ctypes

    from .screen import _exe_for_pid
    user32 = ctypes.windll.user32
    want = re.sub(r"[^a-z0-9]", "", name.lower()).replace("google", "")
    hits = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe = re.sub(r"[^a-z0-9]", "", Path(_exe_for_pid(pid.value)).stem.lower())
            if want and (exe == want or exe.startswith(want) or want.startswith(exe)) and exe != "electron":
                hits.append(hwnd)
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    for h in hits:
        user32.PostMessageW(h, 0x0010, 0, 0)        # WM_CLOSE
    return f"Closed {name}." if hits else f"I don't see {name} open."


# --- D45: other windows: list, switch to, minimize / maximize / restore ---------------
# Shell surfaces, not windows to act on: the tray overflow, the taskbar, Start and Search.
# After closing Spotify the tray popup was in front, and three requests ran against it.
SHELL_CLASSES = {"NotifyIconOverflowWindow", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow",
                 "TopLevelWindowForOverflowXamlIsland", "Progman", "WorkerW", "XamlExplorerHostIslandWindow"}


def top_windows() -> list[tuple[int, str, str, str]]:
    """(hwnd, exe, title, class) of the visible, titled top-level windows, front first."""
    import ctypes

    from .screen import _exe_for_pid
    user32 = ctypes.windll.user32
    out: list[tuple[int, str, str, str]] = []

    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if not user32.IsWindowVisible(hwnd) or not n or user32.GetWindow(hwnd, 4):     # 4: GW_OWNER
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in SHELL_CLASSES:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append((int(hwnd), _exe_for_pid(pid.value), title.value, cls.value))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    return out


def pick_window(name: str, windows: list[tuple[int, str, str, str]]) -> tuple[int, str, str, str] | None:
    """The window an app name means: its exe, then its title, then the closest spelling."""
    from .insights import app_name
    want = re.sub(r"[^a-z0-9]", "", (name or "").lower()).replace("google", "")
    if not want:
        return None
    labels = [(w, re.sub(r"[^a-z0-9]", "", app_name(w[1]).lower()).replace("google", "")) for w in windows]
    for test in (lambda lab, w: lab == want, lambda lab, w: lab.startswith(want) or want.startswith(lab),
                 lambda lab, w: want in re.sub(r"[^a-z0-9]", "", w[2].lower())):
        hit = next((w for w, lab in labels if lab and test(lab, w)), None)
        if hit:
            return hit
    close = difflib.get_close_matches(want, [lab for _, lab in labels if lab], n=1, cutoff=0.6)
    return next((w for w, lab in labels if close and lab == close[0]), None)


def window_state(hwnd: int, state: str) -> bool:
    """Minimize / maximize / restore through UI Automation's WindowPattern (invariant 12)."""
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        wp = auto.ControlFromHandle(hwnd).GetPattern(auto.PatternId.WindowPattern)
        if not wp:
            return False
        want = {"restore": 0, "maximize": 1, "minimize": 2}[state]
        wp.SetWindowVisualState(want)
        try:
            return int(wp.WindowVisualState) == want          # D47: read it back, don't assume
        except Exception:
            return True


def focus_window(hwnd: int) -> bool:
    """Bring a window to the front through UI Automation: restore it if minimized, then SetFocus."""
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        c = auto.ControlFromHandle(hwnd)
        wp = c.GetPattern(auto.PatternId.WindowPattern)
        if wp and wp.WindowVisualState == 2:            # minimized
            wp.SetWindowVisualState(0)
        c.SetFocus()
        return True


# --- opening apps ----------------------------------------------------------------

def _start_menu() -> list[Path]:
    roots = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
             Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs"]
    return [p for r in roots if r.exists() for p in r.rglob("*.lnk")]


def find_app(name: str, shortcuts: list[Path] | None = None) -> Path | None:
    """A Start-menu shortcut for "Chrome", "spotify", "VS Code": exact, then starts
    with, then the closest spelling. Uninstallers and help links are never picked."""
    want = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    want = {"vs code": "visual studio code", "vscode": "visual studio code", "chrome": "google chrome",
            "word": "word", "excel": "excel"}.get(want, want)
    if not want:
        return None
    links = [p for p in (shortcuts if shortcuts is not None else _start_menu())
             if not re.search(r"uninstall|help|readme|documentation|release notes", p.stem, re.I)]
    names = {p: re.sub(r"[^a-z0-9 ]", "", p.stem.lower()) for p in links}
    for test in (lambda n: n == want, lambda n: n.startswith(want), lambda n: want in n.split()):
        hits = sorted((p for p, n in names.items() if test(n)), key=lambda p: len(p.stem))
        if hits:
            return hits[0]
    close = difflib.get_close_matches(want, list(names.values()), n=1, cutoff=0.8)
    return next((p for p, n in names.items() if close and n == close[0]), None)


def open_app(name: str) -> str:
    """Start an app you named. Opening isn't input to another app; it's what you asked."""
    link = find_app(name)
    if link:
        os.startfile(str(link))
        return f"Opening {link.stem}."
    # Store apps (Spotify, WhatsApp) have no shortcut but register a link type
    # ("spotify:"); only one that exists is opened, or Windows asks for an app.
    proto = re.sub(r"[^a-z0-9]", "", name.lower())
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, proto) as k:
            winreg.QueryValueEx(k, "URL Protocol")
    except OSError:
        return f"I couldn't find an app called “{name}”."
    os.startfile(f"{proto}:")
    return f"Opening {name.strip().title()}."
