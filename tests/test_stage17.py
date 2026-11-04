"""D65 check: Jimmy repairs its own camera; no flashing consoles; a lighter overlay and start.
No webcam, no network, no registry writes.

    .venv\\Scripts\\python.exe tests\\test_stage17.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ambient import agent, config, selfcheck  # noqa: E402


class _Install:
    """Stands in for jimmy.install: an installed copy with a settings.json in memory."""
    class _Path:
        def exists(self):
            return True

    def __init__(self, **s):
        self.s = {"webcam": True, "camera_index": 0, **s}
        self.SETTINGS = self._Path()

    def settings(self):
        return dict(self.s)

    def save_settings(self, changes):
        self.s.update(changes)
        return dict(self.s)


class _Bus:
    def __init__(self, state=None, running=True):
        self._presence = {"state": state} if state else {}
        self._presence_obj = object() if running else None
        self.started = []

    def start_presence(self, camera=None):
        self.started.append(camera)
        self._presence_obj = object()
        return True


def _with(fakes: dict, fn):
    """Run fn with module attributes swapped (selfcheck's helpers, jimmy.install)."""
    import jimmy
    saved = {}
    for (mod, name), val in fakes.items():
        saved[(mod, name)] = getattr(mod, name)
        setattr(mod, name, val)
    real_install = jimmy.install
    try:
        return fn()
    finally:
        for (mod, name), val in saved.items():
            setattr(mod, name, val)
        jimmy.install = real_install


def _run(inst, bus, consent="", holders=(), cameras=None, opened=None):
    import jimmy
    import jimmy.install as real
    from ambient import audio
    jimmy.install, sys.modules["jimmy.install"] = inst, inst
    try:
        return _with({(selfcheck, "_consent"): lambda: consent,
                      (audio, "_holders"): lambda cap: [(h, 1) for h in holders],
                      (selfcheck, "_try_cameras"): lambda first=0: cameras,
                      (os, "startfile"): lambda what: opened.append(what) if opened is not None else None},
                     lambda: (selfcheck.diagnose(bus), selfcheck.repair(bus)))
    finally:
        jimmy.install, sys.modules["jimmy.install"] = real, real


def test_setting_off_is_repaired_without_restart():
    inst, bus = _Install(webcam=False), _Bus(running=False)
    before = config.PRESENCE
    try:
        said, fixed = _run(inst, bus, cameras=0)
        assert "setting is off" in said and "fix it" in said, said
        assert inst.s["webcam"] is True and config.PRESENCE is True, "the setting is saved and applied"
        assert bus.started == [0], "the camera starts at once, no restart"
        assert "switched my webcam setting on" in fixed and "works again" in fixed, fixed
    finally:
        config.PRESENCE = before


def test_windows_privacy_opens_the_page():
    opened = []
    said, fixed = _run(_Install(), _Bus(running=False), consent="Let desktop apps access your camera", opened=opened)
    assert "Windows" in said and opened == ["ms-settings:privacy-webcam"], (said, opened)
    assert "switch on" in fixed


def test_a_call_is_named_not_fought():
    bus = _Bus(running=False)
    said, fixed = _run(_Install(), bus, holders=["C:#Apps#Zoom#Zoom.exe"])
    assert "Zoom" in said and "Zoom" in fixed and not bus.started, (said, fixed)


def test_another_camera_index_is_found_and_kept():
    inst, bus = _Install(), _Bus(state=None, running=True)
    before = config.PRESENCE_CAMERA
    try:
        bus._presence_obj = type("P", (), {"stop": lambda self, wait=False: None})()
        said, fixed = _run(inst, bus, cameras=1)
        assert "isn't giving me pictures" in said, said
        assert inst.s["camera_index"] == 1 and bus.started == [1] and "camera 2" in fixed, (inst.s, fixed)
    finally:
        config.PRESENCE_CAMERA = before


def test_working_camera_says_so():
    said, fixed = _run(_Install(), _Bus(state="present"))
    assert said.startswith("The camera is fine") and "already working" in fixed, (said, fixed)


def test_the_agent_finds_the_tools():
    for line in ("you are allowed to use the camera, fix it", "what is the issue with the camera, show me",
                 "why can't you see me"):
        names = {t["function"]["name"] for t in agent.select_tools(line)}
        assert {"diagnose", "fix_problem"} <= names, (line, names)
    assert {"diagnose", "fix_problem"} <= agent.JIMMY_NAMES


def test_hidden_consoles_under_pythonw():
    from jimmy import install
    seen = []
    real = subprocess.Popen.__init__
    subprocess.Popen.__init__ = lambda self, *a, creationflags=0, **k: seen.append(creationflags)
    had = getattr(subprocess.Popen, "_jimmy_hidden", False)
    subprocess.Popen._jimmy_hidden = False
    try:
        install.hide_consoles()
        subprocess.Popen.__init__(object(), ["x"])
        subprocess.Popen.__init__(object(), ["x"], creationflags=0x200)
        assert seen == [0x08000000, 0x08000200], seen
    finally:
        subprocess.Popen.__init__ = real
        subprocess.Popen._jimmy_hidden = had


def test_what_changed_in_the_overlay_and_launcher():
    ov = ROOT / "overlay"
    main = (ov / "main.cjs").read_text(encoding="utf-8")
    assert "if (over === overUi) return;" in main, "the click-through toggle only on a change"
    app = (ov / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "setTimeout(flushDelta, 60)" in app and 'ev.type !== "answer_delta" && pend.current.text' in app
    css = (ov / "src" / "index.css").read_text(encoding="utf-8")
    assert "background-position" not in css, "no per-frame gradient repaint"
    launcher = (ov / "launcher.cjs").read_text(encoding="utf-8")
    start = launcher[launcher.index("function startJimmy"):launcher.index("// --- the onboarding window")]
    assert "startOllama(" not in start and "JIMMY_OLLAMA_EXE" in start, "Python starts Ollama, hidden"
    bus = (ROOT / "ambient" / "bus.py").read_text(encoding="utf-8")
    assert "creationflags=0x08000000" in bus and "power.priority(low=True)" in bus


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
