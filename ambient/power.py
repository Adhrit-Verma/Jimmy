"""How hard Jimmy may work the PC right now (D47).

- `background()`: put the calling thread in Windows' efficiency mode (EcoQoS: efficient
  cores, lower clocks) at below-normal priority. For work nobody is waiting on:
  indexing, compaction, the wiki, the deadline scan. Never the voice path.
- `on_battery()`, `cpu_busy()`, `constrained()`: when to do less (skip indexing, look
  through the webcam half as often).
- `user_idle_s()`: seconds since the last keyboard or mouse input, for a slower tick.

Everything is a no-op that answers "not constrained" off Windows or if a call fails:
it can only make Jimmy lighter, never stop it.
"""
from __future__ import annotations

import ctypes
import os
import threading
import time

from . import config

_WIN = os.name == "nt"


class _ThrottleState(ctypes.Structure):
    _fields_ = [("Version", ctypes.c_ulong), ("ControlMask", ctypes.c_ulong), ("StateMask", ctypes.c_ulong)]


def background() -> bool:
    """EcoQoS + below-normal priority for the calling thread. True if Windows took it."""
    if not _WIN or not config.ECO_BACKGROUND:
        return False
    try:
        k32 = ctypes.windll.kernel32
        th = k32.GetCurrentThread()
        k32.SetThreadPriority(th, -1)                    # THREAD_PRIORITY_BELOW_NORMAL
        st = _ThrottleState(1, 0x1, 0x1)                 # EXECUTION_SPEED: on (EcoQoS)
        return bool(k32.SetThreadInformation(th, 3, ctypes.byref(st), ctypes.sizeof(st)))  # ThreadPowerThrottling
    except Exception:
        return False


def on_battery() -> bool:
    if not _WIN:
        return False

    class _Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    try:
        s = _Status()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return False
        return s.ACLineStatus == 0                       # 0 offline, 1 online, 255 unknown
    except Exception:
        return False


class _Cpu:
    """System CPU use from GetSystemTimes, sampled at most every few seconds."""

    def __init__(self):
        self._last: tuple[int, int, int] | None = None
        self._busy_since: float | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _times() -> tuple[int, int, int] | None:
        ft = [ctypes.c_ulonglong() for _ in range(3)]
        if not ctypes.windll.kernel32.GetSystemTimes(*[ctypes.byref(x) for x in ft]):
            return None
        return ft[0].value, ft[1].value, ft[2].value      # idle, kernel (includes idle), user

    def busy(self) -> bool:
        """System CPU above CPU_BUSY_PCT for CPU_BUSY_S: another app needs the machine."""
        if not _WIN:
            return False
        with self._lock:
            try:
                now = self._times()
            except Exception:
                return False
            if now is None:
                return False
            last, self._last = self._last, now
            if last is None:
                return False
            idle, total = now[0] - last[0], (now[1] - last[1]) + (now[2] - last[2])
            pct = 100.0 * (1 - idle / total) if total > 0 else 0.0
            t = time.monotonic()
            if pct < config.CPU_BUSY_PCT:
                self._busy_since = None
                return False
            self._busy_since = self._busy_since or t
            return t - self._busy_since >= config.CPU_BUSY_S


_cpu = _Cpu()
_cache: dict[str, tuple[float, bool]] = {}


def cpu_busy() -> bool:
    return _cpu.busy()


def constrained() -> bool:
    """On battery, or the PC is busy with something else: do the optional work later.
    Cached for 5 s; cheap to ask from any loop."""
    if not config.LOAD_AWARE:
        return False
    hit = _cache.get("c")
    if hit and time.monotonic() - hit[0] < 5:
        return hit[1]
    val = on_battery() or cpu_busy()
    _cache["c"] = (time.monotonic(), val)
    return val


def user_idle_s() -> float:
    """Seconds since the last keyboard or mouse input (0 if unknown)."""
    if not _WIN:
        return 0.0

    class _Last(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    try:
        li = _Last(ctypes.sizeof(_Last), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return 0.0
        return max(0.0, ((ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF) - li.dwTime) / 1000.0)
    except Exception:
        return 0.0
