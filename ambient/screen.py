"""Screen -> text, early.

A vision model does not fit in 6 GB beside Whisper, so the screen becomes text
here and only text travels onward. UI Automation gives exact strings and is the
Windows advantage over the macOS original; OCR is the fallback for canvas-rendered
apps and video, nothing more.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from . import config

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_exe_cache: dict[int, str] = {}


# --- active window (plain Win32; no UIA needed, so it stays cheap) --------

def _exe_for_pid(pid: int) -> str:
    if pid in _exe_cache:
        return _exe_cache[pid]
    name = ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = Path(buf.value).name
        finally:
            kernel32.CloseHandle(h)
    if len(_exe_cache) > 512:
        _exe_cache.clear()
    _exe_cache[pid] = name
    return name


class ActiveWindow(NamedTuple):
    hwnd: int
    app: str
    title: str
    cls: str = ""                  # D45: the window class, to tell a shell popup from an app


def active_window() -> ActiveWindow:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ActiveWindow(0, "", "")
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    return ActiveWindow(hwnd, _exe_for_pid(pid.value), buf.value, cls.value)


def is_shell(aw: ActiveWindow) -> bool:
    """D45: the tray overflow, taskbar, Start or Search in front: not a window to read or
    act on. (After closing Spotify, the tray popup was captured 16 times and three
    requests ran against it.)"""
    from .act import SHELL_CLASSES
    return getattr(aw, "cls", "") in SHELL_CLASSES or (
        (aw.app or "").lower() == "explorer.exe" and (aw.title or "").rstrip(".") == "System tray overflow window")


def is_locked() -> bool:
    """True while Windows is locked (D32): the input desktop can't be switched to.
    Nothing on screen then, and the mic would only hear an empty room."""
    h = user32.OpenInputDesktop(0, False, 0x0100)          # DESKTOP_SWITCHDESKTOP
    if not h:
        return True
    try:
        return not user32.SwitchDesktop(h)
    finally:
        user32.CloseDesktop(h)


def focused_is_password() -> bool:
    """True if keyboard focus is in a password box (D32): treated like an excluded
    surface, so neither the screen nor a spoken OTP is captured meanwhile."""
    try:
        import uiautomation as auto
        c = auto.GetFocusedControl()
        return bool(c and c.Element.CurrentIsPassword)
    except Exception:
        return False


def _uia_scroll(hwnd: int, down: bool) -> bool:
    """D40: scroll the biggest part of the window that scrolls (a page, a chat) by a
    page, through UI Automation: no input event, so it doesn't matter where your
    pointer is or which box has the keyboard. Measured: Claude's "Chat messages"
    and a Chrome page, found in ~0.1 s; a page down and up restored the exact place."""
    try:
        import uiautomation as auto
        from uiautomation.uiautomation import _AutomationClient
        with auto.UIAutomationInitializerInThread():
            wake_accessibility(hwnd)
            root = auto.ControlFromHandle(hwnd)
            uia = _AutomationClient.instance().IUIAutomation
            found = root.Element.FindAll(4, uia.CreatePropertyCondition(        # 4: all descendants
                auto.PropertyId.IsScrollPatternAvailableProperty, True))
            best = None
            for i in range(found.Length):
                c = auto.Control.CreateControlFromElement(found.GetElement(i))
                sp = c.GetPattern(auto.PatternId.ScrollPattern)
                r = c.BoundingRectangle
                area = max(0, r.width()) * max(0, r.height())
                if sp and sp.VerticallyScrollable and (best is None or area > best[0]):
                    best = (area, sp)
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            whole = max(1, (rect.right - rect.left) * (rect.bottom - rect.top))
            # A small list isn't "the window" (VS Code's editor exposes no scrolling; the
            # biggest scroller there is a side list): leave those to the mouse wheel.
            if best is None or best[0] < 0.15 * whole:
                return False
            sp, before = best[1], best[1].VerticalScrollPercent
            if (down and before >= 99.9) or (not down and 0 <= before <= 0.1):
                return True                       # already at that end: nothing to do
            sp.Scroll(auto.ScrollAmount.NoAmount,
                      auto.ScrollAmount.LargeIncrement if down else auto.ScrollAmount.LargeDecrement)
            return sp.VerticalScrollPercent != before
    except Exception as exc:
        print(f"[scroll] UI Automation: {type(exc).__name__}: {exc}")
        return False


def scroll_active(down: bool, notches: int = 5) -> bool:
    """Scroll the window you're on (D35: "Jimmy, scroll down" with nothing of Jimmy's
    to scroll). The only input Jimmy ever sends to another app, and only when asked:
    no clicks, no typing. D40: through UI Automation first (it scrolled nothing in
    the Claude app when the pointer sat over the message box); the mouse wheel, or
    Page Down/Up if the pointer isn't over that window, only for windows without it."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    if _uia_scroll(hwnd, down):
        return True
    pt, rect = wintypes.POINT(), wintypes.RECT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if rect.left <= pt.x < rect.right and rect.top <= pt.y < rect.bottom:
        user32.mouse_event(0x0800, 0, 0, (-120 if down else 120) * notches, 0)   # MOUSEEVENTF_WHEEL
    else:
        vk = 0x22 if down else 0x21                                              # VK_NEXT / VK_PRIOR
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)                                          # KEYEVENTF_KEYUP
    return True


def clean_url(raw: str) -> str | None:
    """What an address bar showed, as a link to reopen (D32). Query and fragment
    are dropped (that's where tokens live); only http(s) pages are kept."""
    from urllib.parse import urlsplit
    raw = (raw or "").strip()
    if not raw or " " in raw:
        return None                       # a search being typed, not a page
    if "://" not in raw:
        raw = "https://" + raw
    u = urlsplit(raw)
    if u.scheme not in ("http", "https") or "." not in u.netloc:
        return None
    return f"{u.scheme}://{u.netloc}{u.path}"[:500]


# --- UI Automation text ---------------------------------------------------

# Buttons and menu items are left out: in the first real hour they were the bulk
# of the boilerplate (Minimize, Maximize, Close, Back, Forward, Filter ... in
# nearly every capture, 44 % of all text). Their children are still walked.
TEXT_TYPES = {
    "TextControl", "EditControl", "DocumentControl", "ListItemControl",
    "TreeItemControl", "TabItemControl", "HyperlinkControl", "DataItemControl",
    "CheckBoxControl", "RadioButtonControl", "HeaderItemControl",
    "GroupControl", "StatusBarControl",
}
_URL_HINTS = ("address and search bar", "address field", "search or enter",
              "address bar", "enter address", "url")


class WindowText(NamedTuple):
    text: str
    url: str
    nodes: int
    elapsed: float
    truncated: bool


WM_GETOBJECT = 0x003D
OBJID_CLIENT = -4
SMTO_ABORTIFHUNG = 0x0002
_woken: set[int] = set()


def wake_accessibility(hwnd: int) -> None:
    """Tell a Chromium/Electron window that an assistive technology is present.

    Chromium keeps its accessibility engine off until something asks for it, and
    until it is on the renderer exposes *nothing* -- a live Electron window walked
    24 nodes cold and 317 once woken. This is the signal screen readers send.

    The cost is real and lands on the target app: it now builds and maintains an
    accessibility tree. That is the price of exact text instead of OCR guesses.
    """
    if not hwnd or hwnd in _woken:
        return
    _woken.add(hwnd)
    if len(_woken) > 256:
        _woken.clear()
        _woken.add(hwnd)
    result = ctypes.c_size_t()
    # Timeout + ABORTIFHUNG: a wedged app must never stall the capture loop.
    user32.SendMessageTimeoutW(wintypes.HWND(hwnd), WM_GETOBJECT, 0, OBJID_CLIENT,
                               SMTO_ABORTIFHUNG, 200, ctypes.byref(result))


def _value_of(ctrl) -> str:
    """Name first; fall back to the value pattern for editable controls."""
    try:
        name = (ctrl.Name or "").strip()
    except Exception:
        name = ""
    try:
        if ctrl.ControlTypeName in ("EditControl", "DocumentControl"):
            pattern = ctrl.GetValuePattern()
            val = (pattern.Value or "").strip() if pattern else ""
            if val and val != name:
                return f"{name} {val}".strip() if name else val
    except Exception:
        pass
    return name


def window_text(hwnd: int,
                max_nodes: int = config.UIA_MAX_NODES,
                max_depth: int = config.UIA_MAX_DEPTH,
                budget_s: float = config.UIA_BUDGET_S) -> WindowText:
    """Breadth-first walk of the foreground window, hard-capped three ways.

    ponytail: caps on node count, depth and wall clock rather than anything
    adaptive. A deep Electron tree gets truncated and OCR picks up the slack.
    Make it adaptive only if replay shows real windows losing text that matters.
    """
    import uiautomation as auto

    started = time.perf_counter()
    wake_accessibility(hwnd)  # no-op after the first sight of this window
    parts: list[str] = []
    seen: set[str] = set()
    url = ""
    nodes = 0
    truncated = False
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception:
        root = None
    if root is None:
        return WindowText("", "", 0, time.perf_counter() - started, False)

    queue = [(root, 0)]
    while queue:
        if nodes >= max_nodes or (time.perf_counter() - started) > budget_s:
            truncated = True
            break
        ctrl, depth = queue.pop(0)
        nodes += 1
        # D38: the wrapper class already says the type (it was chosen from it). The
        # property asked Windows again: 134 ms per 800 nodes, a third of the budget.
        ctype = type(ctrl).__name__
        if ctype in TEXT_TYPES:
            val = _value_of(ctrl)
            if val and len(val) > 1 and val not in seen:
                seen.add(val)
                parts.append(val)
            if not url and ctype == "EditControl":
                try:
                    nm = (ctrl.Name or "").lower()
                except Exception:
                    nm = ""
                if any(h in nm for h in _URL_HINTS):
                    url = val
        if depth < max_depth:
            try:
                for child in ctrl.GetChildren():
                    queue.append((child, depth + 1))
            except Exception:
                pass

    return WindowText("\n".join(parts), url, nodes,
                      time.perf_counter() - started, truncated)


# --- OCR fallback ---------------------------------------------------------

_ocr_state: dict[str, object] = {}


def _engines() -> list[str]:
    """D51 (A7): which OCR engines to try, in order. "auto": Windows' own (built in,
    offline, no install beyond `pip install winocr`), then Tesseract (rarely installed)."""
    want = config.OCR_ENGINE.lower()
    return ["windows", "tesseract"] if want == "auto" else [want]


def _probe(engine: str) -> None:
    if engine == "windows":
        import winocr  # noqa: F401  (Windows.Media.Ocr through WinRT)
    elif engine == "tesseract":
        import pytesseract
        pytesseract.get_tesseract_version()
    else:
        raise ValueError(f"unknown OCR engine {engine!r}")


def ocr_engine() -> str | None:
    """The first engine that works here, probed once; None when OCR is inert."""
    if "engine" not in _ocr_state:
        _ocr_state["engine"], why = None, []
        for e in _engines():
            try:
                _probe(e)
                _ocr_state["engine"] = e
                break
            except Exception as exc:
                why.append(f"{e}: {type(exc).__name__}: {exc}")
        _ocr_state["why"] = "; ".join(why)
    return _ocr_state["engine"]


def ocr_available() -> bool:
    return ocr_engine() is not None


def _ocr_windows(gray: np.ndarray) -> str:
    import winocr
    res = winocr.recognize_cv2_sync(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGRA), config.OCR_LANG)
    lines = res.get("lines") if isinstance(res, dict) else getattr(res, "lines", None)
    if lines:
        return "\n".join(str(ln.get("text") if isinstance(ln, dict) else getattr(ln, "text", "")) for ln in lines)
    return str((res.get("text") if isinstance(res, dict) else getattr(res, "text", "")) or "")


def ocr(bgr: np.ndarray) -> str:
    """Only for canvas-rendered apps and video, where UIA has nothing to say. Always
    handed the blurred frame (faces can't be read)."""
    if not config.OCR_ENABLED:
        return ""
    engine = ocr_engine()
    if engine is None:
        return ""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    if gray.shape[1] > 1600:
        s = 1600 / gray.shape[1]
        gray = cv2.resize(gray, (1600, int(gray.shape[0] * s)), interpolation=cv2.INTER_AREA)
    try:
        if engine == "windows":
            return _ocr_windows(gray).strip()
        import pytesseract
        return pytesseract.image_to_string(gray).strip()
    except Exception:
        return ""


# --- frames ---------------------------------------------------------------

def signature(bgr: np.ndarray) -> np.ndarray:
    """A small grey copy of the frame: all the change gate compares (~14 KB)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, config.GATE_GRID, interpolation=cv2.INTER_AREA)


def changed_pct(a: np.ndarray, b: np.ndarray) -> float:
    """Percent of signature pixels that moved by more than GATE_PIXEL_DELTA."""
    if a.shape != b.shape:
        return 100.0
    return 100.0 * np.count_nonzero(cv2.absdiff(a, b) > config.GATE_PIXEL_DELTA) / a.size


class ScreenSource:
    """DXGI desktop duplication, pulled on demand.

    Pull beats the push API here: we want a frame every 2s, not every vsync.
    """

    def __init__(self, monitor_index: int | None = None):
        import windows_capture as wc
        self._wc = wc
        self._monitor = monitor_index
        self._session = wc.DxgiDuplicationSession(monitor_index=monitor_index) \
            if monitor_index is not None else wc.DxgiDuplicationSession()

    def grab(self, timeout_ms: int = 200) -> np.ndarray | None:
        """BGR frame, or None if the desktop produced nothing this interval."""
        try:
            frame = self._session.acquire_frame(timeout_ms)
        except Exception:
            # Device loss: resolution change, GPU reset, or the secure desktop
            # (UAC / lock screen), which we are not permitted to duplicate anyway.
            try:
                self._session.recreate()
            except Exception:
                pass
            return None
        if frame is None:
            return None
        arr = frame.to_numpy()
        return np.ascontiguousarray(arr[:, :, :3]) if arr.shape[2] == 4 else arr


def save_thumb(bgr: np.ndarray, ts_ms: int, thumb_dir: Path | None = None, width: int | None = None) -> str:
    """Write the (already blurred) frame as a small JPEG. Returns a relative path.
    `width` (D52): narrower than THUMB_WIDTH for a frame whose text didn't change."""
    width = width or config.THUMB_WIDTH
    root = Path(thumb_dir or config.THUMB_DIR)
    day = time.strftime("%Y%m%d", time.localtime(ts_ms / 1000))
    out_dir = root / day
    out_dir.mkdir(parents=True, exist_ok=True)
    h, w = bgr.shape[:2]
    if w > width:
        s = width / w
        bgr = cv2.resize(bgr, (width, max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)
    path = out_dir / f"{ts_ms}.jpg"
    opts = [cv2.IMWRITE_JPEG_QUALITY, config.THUMB_JPEG_QUALITY]
    if config.THUMB_JPEG_OPTIMIZE:
        opts += [cv2.IMWRITE_JPEG_OPTIMIZE, 1, cv2.IMWRITE_JPEG_PROGRESSIVE, 1]
    cv2.imwrite(str(path), bgr, opts)
    return str(path.relative_to(root.parent)) if root.parent in path.parents else str(path)
