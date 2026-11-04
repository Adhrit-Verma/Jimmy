"""D67 check: the camera switch is set before OpenCV loads; the camera API falls back; Quit ends the
process; the diagnostic report (no captured text, masked user); Claude Desktop's MCP tool.
No webcam, no network.

    .venv\\Scripts\\python.exe tests\\test_stage19.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = sys.executable


def test_switch_is_set_before_opencv_loads():
    code = ("import sys, ambient.bus; import os; "
            "print(os.environ.get('OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS'), 'cv2' in sys.modules)")
    env = {k: v for k, v in os.environ.items() if k != "OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"}
    out = subprocess.run([PY, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env).stdout.split()
    assert out[-2:] == ["0", "True"], out
    src = (ROOT / "jimmy" / "install.py").read_text(encoding="utf-8")
    assert src.index("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS") < src.index("def "), "at import, first"


def test_camera_api_falls_back():
    from ambient import presence
    tried = []

    class Cap:
        def __init__(self, i, api):
            tried.append(api)
            self.api = api

        def isOpened(self):
            return self.api == presence.cv2.CAP_DSHOW

        def release(self):
            pass
    real = presence.cv2.VideoCapture
    presence.cv2.VideoCapture = Cap
    try:
        cap, api = presence.open_camera(0)
        assert api == presence.cv2.CAP_DSHOW and tried == [presence.cv2.CAP_MSMF, presence.cv2.CAP_DSHOW]
        tried.clear()
        cap, api = presence.open_camera(0, first=presence.cv2.CAP_DSHOW)
        assert tried == [presence.cv2.CAP_DSHOW], "the other API first after a camera stopped"
    finally:
        presence.cv2.VideoCapture = real
    src = (ROOT / "ambient" / "presence.py").read_text(encoding="utf-8")
    assert "self._api_first = cv2.CAP_DSHOW if used == cv2.CAP_MSMF else cv2.CAP_MSMF" in src


def test_quit_ends_the_process_and_its_ollama():
    main = (ROOT / "ambient" / "__main__.py").read_text(encoding="utf-8")
    run = main[main.index("counters = bus.run("):]
    assert "os._exit(0)" in run[:600], "nothing left waiting can keep Jimmy alive after Quit"
    bus = (ROOT / "ambient" / "bus.py").read_text(encoding="utf-8")
    assert "self._ollama = subprocess.Popen(" in bus and "ollama.terminate()" in bus


def test_report_has_facts_not_captures():
    from ambient import report
    text = report.build()
    for part in ("## Jimmy and this PC", "## Camera", "Windows says using the webcam", "## The end of Jimmy's log"):
        assert part in text, part
    user = os.environ.get("USERNAME", "")
    if len(user) >= 3:
        assert user not in text, "the user name is masked"
    url = report.issue_url(report.save())
    assert url.startswith("https://github.com/Adhrit-Verma/Jimmy/issues/new?") and len(url) < 16_000


def test_claude_desktop_can_read_it():
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "diagnostic_report", "arguments": {}}}]
    out = subprocess.run([PY, "-m", "jimmy", "mcp"], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                         capture_output=True, text=True, cwd=ROOT, timeout=60).stdout.splitlines()
    replies = {r["id"]: r["result"] for r in map(json.loads, out)}
    assert "diagnostic_report" in [t["name"] for t in replies[1]["tools"]]
    assert "# Jimmy diagnostic report" in replies[2]["content"][0]["text"] and not replies[2]["isError"]


def test_by_voice():
    from ambient import agent
    for q in ("make a diagnostic report", "send the report to the developer", "collect the logs"):
        names = {t["function"]["name"] for t in agent.select_tools(q)}
        assert {"make_report", "send_report"} <= names, (q, names)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
