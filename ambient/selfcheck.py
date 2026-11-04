"""D65: Jimmy checks itself and repairs what it can, so a user never has to.

"Jimmy, why can't you see me?" -> `diagnose`: every reason the camera can be off, in order,
in plain words. "You're allowed to use the camera" / "fix it" -> `repair`: Jimmy fixes what is
its own to fix, at once, without a restart:
  - its webcam setting is off (Lite, an onboarding box, Settings)  -> on, and the camera starts
  - the camera thread died or the camera didn't open                -> try cameras 0-3, keep the one that works
and points at what only the user may change:
  - Windows' camera privacy denies desktop apps                     -> opens that Settings page
  - another app (a call) has the camera                             -> names it; Jimmy takes it back after
Nothing here sends anything anywhere; it reads the registry, the settings and the camera.
"""
from __future__ import annotations

import os
import time

from . import config

_CONSENT = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"
_WORKING = ("present", "away", "watched", "stranger")       # presence states that prove the camera works


def _consent() -> str:
    """"" if Windows lets desktop apps use the camera, else which switch is off."""
    try:
        import winreg
    except ImportError:
        return ""
    for path, label in ((_CONSENT, "Camera access"), (_CONSENT + r"\NonPackaged", "Let desktop apps access your camera")):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                if str(winreg.QueryValueEx(k, "Value")[0]).lower() == "deny":
                    return label
        except OSError:
            continue
    return ""


def _setting_on() -> bool:
    from jimmy import install
    return bool(install.settings().get("webcam", True)) if install.SETTINGS.exists() else bool(config.PRESENCE)


def _try_cameras(first: int = 0) -> int | None:
    """The first camera (the chosen one, then 0-3) that opens and gives a frame. Only when
    Jimmy isn't holding a camera itself: a working camera is never swapped for an IR or virtual one."""
    from .presence import open_camera
    for i in [first] + [n for n in range(4) if n != first]:
        cap, _ = open_camera(i)
        if cap is None:
            continue
        try:
            for _ in range(5):                       # some cameras need a frame or two to start
                ok, frame = cap.read()
                if ok and frame is not None:
                    return i
                time.sleep(0.1)
        finally:
            cap.release()
    return None


def camera(bus) -> list[dict]:
    """Findings, most decisive first: {"check", "ok", "say", "fix"} ("fix": "jimmy" = Jimmy can,
    "user" = only the user can, "" = nothing to fix)."""
    from .audio import _holders, app_label
    out = []
    on = _setting_on()
    out.append({"check": "setting", "ok": on, "fix": "" if on else "jimmy",
                "say": "My webcam setting is on." if on else
                "My own webcam setting is off (the Lite profile or a setup choice turns it off)."})
    denied = _consent()
    out.append({"check": "windows", "ok": not denied, "fix": "user" if denied else "",
                "say": "Windows lets me use the camera." if not denied else
                f"Windows' camera privacy has “{denied}” switched off, so no desktop app can use it."})
    held = [app_label(k) for k, _ in _holders("webcam")]
    out.append({"check": "busy", "ok": not held, "fix": "",
                "say": "No other app has the camera." if not held else
                f"{', '.join(held)} is using the camera; I give it back to calls and take it again after."})
    info = dict(getattr(bus, "_presence", None) or {})
    running = getattr(bus, "_presence_obj", None) is not None
    state, why = info.get("state"), info.get("why") or ""
    working = running and state in _WORKING
    say = (f"The camera is working: {state}." if working else
           "My camera thread isn't running." if not running else
           f"The camera isn't giving me pictures{': ' + why if why else ''}.")
    out.append({"check": "camera", "ok": working, "fix": "" if working else "jimmy", "say": say})
    return out


def diagnose(bus) -> str:
    """What's wrong, spoken: the problems, or that all is well."""
    found = camera(bus)
    bad = [f for f in found if not f["ok"]]
    if not bad:
        return "The camera is fine: " + found[-1]["say"][0].lower() + found[-1]["say"][1:]
    tail = " Say “fix it” and I'll repair what I can." if any(f["fix"] == "jimmy" for f in bad) else ""
    return " ".join(f["say"] for f in bad) + tail


def repair(bus) -> str:
    """Fix what Jimmy may fix; open the page for what only the user may change. Spoken result."""
    from jimmy import install
    said = []
    found = {f["check"]: f for f in camera(bus)}
    if not found["setting"]["ok"]:
        if install.SETTINGS.exists():
            install.save_settings({"webcam": True})
        config.PRESENCE = True
        said.append("I've switched my webcam setting on.")
    if not found["windows"]["ok"]:
        try:
            os.startfile("ms-settings:privacy-webcam")
        except OSError:
            pass
        return " ".join(said + ["Windows is blocking the camera for desktop apps. I've opened the page: switch on "
                                "“Camera access” and “Let desktop apps access your camera”, "
                                "then say “fix it” again."])
    if not found["busy"]["ok"]:
        return " ".join(said + [found["busy"]["say"]])
    if found["camera"]["ok"]:
        return " ".join(said + ["The camera is already working."]) if said else "The camera is already working."
    old = getattr(bus, "_presence_obj", None)
    if old:                                       # let go of the camera before trying them all
        old.stop(wait=True)
        bus._presence_obj = None
    idx = _try_cameras(first=config.PRESENCE_CAMERA)
    if idx is None:
        bus.start_presence()                      # as it was; it retries on its own
        return " ".join(said + ["No camera gave me a picture. Is it plugged in, or covered by a privacy "
                                "shutter or switch?"])
    if idx != config.PRESENCE_CAMERA:
        config.PRESENCE_CAMERA = idx
        if install.SETTINGS.exists():
            install.save_settings({"camera_index": idx})
    bus.start_presence(camera=idx)
    return " ".join(said + [f"The camera works again{' (camera ' + str(idx + 1) + ')' if idx else ''}."])


if __name__ == "__main__":                        # python -m ambient.selfcheck: read-only, on this PC
    class _NoBus:
        _presence, _presence_obj = None, None
    for f in camera(_NoBus()):
        print(f"{'ok ' if f['ok'] else 'BAD'}  {f['check']:8} {f['say']}")
    print("Windows camera consent:", _consent() or "allowed")
