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


def active_window() -> ActiveWindow:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ActiveWindow(0, "", "")
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return ActiveWindow(hwnd, _exe_for_pid(pid.value), buf.value)


# --- UI Automation text ---------------------------------------------------

TEXT_TYPES = {
    "TextControl", "EditControl", "DocumentControl", "ButtonControl", "ListItemControl",
    "TreeItemControl", "TabItemControl", "HyperlinkControl", "DataItemControl",
    "CheckBoxControl", "RadioButtonControl", "MenuItemControl", "HeaderItemControl",
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
        try:
            ctype = ctrl.ControlTypeName
        except Exception:
            continue
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


def ocr_available() -> bool:
    if "ok" not in _ocr_state:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            _ocr_state["ok"] = True
        except Exception as exc:
            _ocr_state["ok"] = False
            _ocr_state["why"] = f"{type(exc).__name__}: {exc}"
    return bool(_ocr_state["ok"])


def ocr(bgr: np.ndarray) -> str:
    """Only for canvas-rendered apps and video, where UIA has nothing to say."""
    if not config.OCR_ENABLED or not ocr_available():
        return ""
    import pytesseract
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if gray.shape[1] > 1600:
        s = 1600 / gray.shape[1]
        gray = cv2.resize(gray, (1600, int(gray.shape[0] * s)), interpolation=cv2.INTER_AREA)
    try:
        return pytesseract.image_to_string(gray).strip()
    except Exception:
        return ""


# --- frames ---------------------------------------------------------------

def dhash(bgr: np.ndarray, size: int = config.DHASH_SIZE) -> int:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    return int.from_bytes(np.packbits(diff).tobytes(), "big")


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


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


def save_thumb(bgr: np.ndarray, ts_ms: int, thumb_dir: Path | None = None) -> str:
    """Write the (already blurred) frame as a small JPEG. Returns a relative path."""
    root = Path(thumb_dir or config.THUMB_DIR)
    day = time.strftime("%Y%m%d", time.localtime(ts_ms / 1000))
    out_dir = root / day
    out_dir.mkdir(parents=True, exist_ok=True)
    h, w = bgr.shape[:2]
    if w > config.THUMB_WIDTH:
        s = config.THUMB_WIDTH / w
        bgr = cv2.resize(bgr, (config.THUMB_WIDTH, max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)
    path = out_dir / f"{ts_ms}.jpg"
    cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, config.THUMB_JPEG_QUALITY])
    return str(path.relative_to(root.parent)) if root.parent in path.parents else str(path)
