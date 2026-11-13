"""D70 check: Jimmy gives the camera away when something else wants it; patch updates.
No webcam, no network.

    .venv\\Scripts\\python.exe tests\\test_stage20.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ambient import agent, audio, presence, screen  # noqa: E402
from jimmy import patch  # noqa: E402


def _wanted(mic=(), title="Editor", running=()):
    saved = audio.mic_holders, screen.active_window, audio._running_images
    audio.mic_holders = lambda: list(mic)
    screen.active_window = lambda: screen.ActiveWindow(1, "x.exe", title)
    audio._running_images = lambda: {p.lower() for p in running}
    try:
        return presence.wanted_elsewhere()
    finally:
        audio.mic_holders, screen.active_window, audio._running_images = saved


def test_who_gets_the_camera():
    assert _wanted() == "", "nothing else wants it: Jimmy's"
    assert "Discord" in _wanted(mic=["C:#Apps#Discord#Discord.exe"]), "a call (another app on the mic)"
    assert _wanted(title="Camera") == "Camera is open", "Windows' Camera app in front"
    assert "obs64" in _wanted(running=[r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"]), "OBS running"
    assert _wanted(title="Camera settings - Chrome") == "", "a title that only mentions the word"


def test_let_go_and_take_back():
    p = presence.Presence(lambda i: None, owner=object())
    assert p.released_until == 0
    p.release()
    assert 29 * 60 < p.released_until - time.time() <= 30 * 60, "30 minutes by default"
    p.release(0)
    assert p.released_until == 0, "take it back"
    for q in ("let go of the camera", "I need my camera for a meeting", "take the camera back"):
        assert {"release_camera", "take_camera"} <= {t["function"]["name"] for t in agent.select_tools(q)}, q


def _zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_patch_swaps_the_code_and_nothing_else():
    with tempfile.TemporaryDirectory() as d:
        inst = Path(d, "App")
        (inst / "resources" / "jimmy" / "ambient").mkdir(parents=True)
        (inst / "resources" / "app.asar").write_bytes(b"old asar")
        (inst / "resources" / "jimmy" / "ambient" / "a.py").write_text("old")
        (inst / "resources" / "jimmy" / "models").mkdir()
        (inst / "resources" / "jimmy" / "models" / "face.onnx").write_bytes(b"kept")
        good = _zip(Path(d, "p.zip"), {"app.asar": b"new asar", "jimmy/ambient/a.py": "new",
                                        "jimmy/jimmy-installed.json": json.dumps({"version": "9"})})
        assert patch.apply(good, inst, wait_s=1) == ""
        assert (inst / "resources" / "app.asar").read_bytes() == b"new asar"
        assert (inst / "resources" / "jimmy" / "ambient" / "a.py").read_text() == "new"
        assert (inst / "resources" / "jimmy" / "models" / "face.onnx").read_bytes() == b"kept", "not in a patch: left alone"
        assert not (inst / "resources" / "app.asar.old").exists()
        for bad in ({"app.asar": b"x", "../evil.txt": "x"}, {"app.asar": b"x", "tools/uv.exe": "x"},
                    {"jimmy/a.py": "x"}):                      # outside, not Jimmy's, no app.asar
            assert patch.apply(_zip(Path(d, "bad.zip"), bad), inst, wait_s=1).startswith("not a Jimmy patch")
        assert (inst / "resources" / "app.asar").read_bytes() == b"new asar", "a refused patch changes nothing"
        assert not Path(d, "evil.txt").exists()


def test_updates_are_small_now():
    pkg = json.loads((ROOT / "overlay" / "package.json").read_text(encoding="utf-8"))
    assert not pkg.get("dependencies"), "bundled by vite: as dependencies they were packed twice (43 MB)"
    upd = (ROOT / "overlay" / "updater.cjs").read_text(encoding="utf-8")
    assert "Jimmy-Patch-${latest}-${base}.zip" in upd and 'p.kind === "patch"' in upd
    build = (ROOT / "installer" / "build.py").read_text(encoding="utf-8")
    assert '"base": base_id()' in build and "def make_patch" in build
    wf = (ROOT / ".github" / "workflows" / "installer.yml").read_text(encoding="utf-8")
    assert "Jimmy-Patch-*.zip" in wf and "the patch wasn't applied" in wf


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
