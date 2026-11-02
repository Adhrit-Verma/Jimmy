"""D63–D64 check: the camera isn't "in use" by an app that's gone or by Jimmy itself;
updates (version, pending update, the off switch, what ships). No network, no webcam.

    .venv\\Scripts\\python.exe tests\\test_stage16.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ambient import audio  # noqa: E402

STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"


class _Key:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_winreg(tree: dict) -> types.ModuleType:
    """tree: registry path -> {"subs": [...]} or {"LastUsedTimeStop": n, "LastUsedTimeStart": n}."""
    m = types.ModuleType("winreg")
    m.HKEY_CURRENT_USER = object()

    def open_key(_root, path):
        if path not in tree:
            raise OSError(path)
        return _Key(path)

    def enum_key(key, i):
        subs = tree[key.path].get("subs", [])
        if i >= len(subs):
            raise OSError("no more")
        return subs[i]

    def query(key, name):
        if name not in tree[key.path]:
            raise OSError(name)
        return tree[key.path][name], 4

    m.OpenKey, m.EnumKey, m.QueryValueEx = open_key, enum_key, query
    return m


def test_alive_by_exe_and_package():
    images = {r"c:\program files\google\chrome\application\chrome.exe",
              r"c:\program files\windowsapps\microsoft.windowscamera_2025.1.0.0_x64__8wekyb3d8bbwe\windowscamera.exe"}
    assert audio._alive(r"C:#Program Files#Google#Chrome#Application#chrome.exe", images)
    assert not audio._alive(r"C:#Users#me#AppData#Local#Discord#app-1.0#Discord.exe", images), "a dead exe"
    assert audio._alive("Microsoft.WindowsCamera_8wekyb3d8bbwe", images)
    assert not audio._alive("MSTeams_8wekyb3d8bbwe", images), "a store app that isn't running"
    assert not audio._alive("Microsoft.WindowsCamera_otherpublisher", images), "same name, other publisher"


def test_holders_skip_gone_apps_and_jimmy():
    me = Path(audio._image_path(os.getpid()))
    own_w = str(me.with_name("pythonw.exe"))           # the installed copy runs pythonw
    np = STORE + r"\NonPackaged"
    key = lambda p: p.replace("\\", "#")                # noqa: E731
    live, dead = r"C:\Apps\Zoom\Zoom.exe", r"C:\Apps\Crashed\Old.exe"
    tree = {
        STORE: {"subs": ["NonPackaged", "MSTeams_8wekyb3d8bbwe", "Microsoft.WindowsCamera_8wekyb3d8bbwe"]},
        np: {"subs": [key(live), key(dead), key(own_w), key(r"C:\Apps\Done\Done.exe")]},
        np + "\\" + key(live): {"LastUsedTimeStop": 0, "LastUsedTimeStart": 5},
        np + "\\" + key(dead): {"LastUsedTimeStop": 0, "LastUsedTimeStart": 6},          # stale: crashed
        np + "\\" + key(own_w): {"LastUsedTimeStop": 0, "LastUsedTimeStart": 7},         # Jimmy itself
        np + "\\" + key(r"C:\Apps\Done\Done.exe"): {"LastUsedTimeStop": 9, "LastUsedTimeStart": 8},
        STORE + r"\MSTeams_8wekyb3d8bbwe": {"LastUsedTimeStop": 0, "LastUsedTimeStart": 10},  # not running
        STORE + r"\Microsoft.WindowsCamera_8wekyb3d8bbwe": {"LastUsedTimeStop": 0, "LastUsedTimeStart": 11},
    }
    images = {live.lower(), r"c:\program files\windowsapps\microsoft.windowscamera_1.0_x64__8wekyb3d8bbwe\cam.exe"}
    real_winreg, real_images = sys.modules.get("winreg"), audio._running_images
    sys.modules["winreg"] = _fake_winreg(tree)
    audio._running_images = lambda: images
    try:
        got = [k for k, _ in audio._holders("webcam")]
        assert got == [key(live), "Microsoft.WindowsCamera_8wekyb3d8bbwe"], got
        assert audio.other_app_using("webcam")
        images.clear()
        images.add(r"c:\somewhere\else.exe")
        assert not audio.other_app_using("webcam"), "every holder gone: the camera is free"
    finally:
        sys.modules["winreg"] = real_winreg
        audio._running_images = real_images


def test_own_keys_include_the_real_image():
    own = audio._own_mic_keys()
    me = audio._image_path(os.getpid())
    assert me and me.replace("\\", "#").lower() in own, (me, own)
    assert me.replace("\\", "#").lower().replace("python.exe", "pythonw.exe") in own, "pythonw too"
    images = audio._running_images()
    assert me.lower() in images and len(images) > 5, "this process is among the running ones"


def _node(script: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, cwd=ROOT / "overlay",
                          env=env, check=True).stdout.strip()


def test_updater_pending_and_switch():
    subprocess.run(["node", str(ROOT / "overlay" / "updater.cjs")], check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as d:
        up = Path(d, "cache", "update")
        up.mkdir(parents=True)
        exe = up / "Jimmy-Setup-1.0.2.exe"
        exe.write_bytes(b"not really a setup")
        import hashlib
        sha = hashlib.sha256(exe.read_bytes()).hexdigest()
        (up / "pending.json").write_text(json.dumps({"version": "1.0.2", "file": str(exe), "sha256": sha}))
        js = f"const u = require('./updater.cjs'); const p = u.pending({json.dumps(d)}, %s); console.log(p ? p.version : 'none')"
        assert _node(js % "'1.0.1'") == "1.0.2", "a newer, verified setup is pending"
        Path(d, "settings.json").write_text(json.dumps({"auto_update": False}))
        assert _node(js % "'1.0.1'") == "none", "auto_update off: nothing installs"
        assert up.exists(), "switched off: the download is left alone"
        Path(d, "settings.json").unlink()
        exe.write_bytes(b"tampered")
        assert _node(js % "'1.0.1'") == "none" and not up.exists(), "a changed file is thrown away"
        up.mkdir(parents=True)
        exe.write_bytes(b"not really a setup")
        (up / "pending.json").write_text(json.dumps({"version": "1.0.2", "file": str(exe), "sha256": sha}))
        assert _node(js % "'1.0.2'") == "none" and not up.exists(), "installed: the leftovers go"
        up.mkdir(parents=True)
        exe.write_bytes(b"not really a setup")
        (up / "pending.json").write_text(json.dumps({"version": "1.0.2", "file": str(exe), "sha256": sha,
                                                     "tried": True}))
        assert _node(js % "'1.0.1'") == "none" and not up.exists(), \
            "a setup that was tried and didn't take never blocks the next start"


def test_what_ships():
    pkg = json.loads((ROOT / "overlay" / "package.json").read_text(encoding="utf-8"))
    assert "updater.cjs" in pkg["build"]["files"], "the packaged app needs the updater"
    from jimmy import install
    assert install.DEFAULTS["auto_update"] is True
    wf = (ROOT / ".github" / "workflows" / "installer.yml").read_text(encoding="utf-8")
    assert "needs: [build, test-clean-machine]" in wf and 'gh release view "v$v"' in wf, \
        "a release only after the clean-machine test, and only for a new version"
    launcher = (ROOT / "overlay" / "launcher.cjs").read_text(encoding="utf-8")
    assert "function download(" not in launcher and "updater.pending(" in launcher


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
