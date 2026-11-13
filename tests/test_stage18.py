"""D66 check: the status dock's numbers (vitals), the update's progress, the pill's signals.
No webcam, no network.

    .venv\\Scripts\\python.exe tests\\test_stage18.py
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ambient import agent, power  # noqa: E402
from ambient.bus import ContextBus as Bus  # noqa: E402
from ambient.db import now_ms  # noqa: E402


def test_process_usage_counts_cpu_and_ram():
    a = power.process_usage()
    sum(i * i for i in range(2_000_000))
    b = power.process_usage()
    assert b[0] > a[0] and b[1] > 10_000_000, (a, b)


def _bus(**over):
    asker = types.SimpleNamespace(followup_until=now_ms() + 30_000, listen_until=0, nav_until=now_ms() + 9_000,
                                  _jim=lambda: types.SimpleNamespace(llm=types.SimpleNamespace(model="m/x", key="k")))
    b = types.SimpleNamespace(_asker=asker, _presence={"state": "present", "contact": True, "faces": 1},
                              _presence_obj=object(), paused_until=0, _audio=None, _curtain=False,
                              counters=types.SimpleNamespace(frames=7))
    b.__dict__.update(over)
    return b


def test_vitals_has_what_the_dock_shows():
    v, prev = Bus.vitals(_bus(), None)
    time.sleep(0.2)
    v, _ = Bus.vitals(_bus(), prev)
    assert v["type"] == "vitals" and v["ram_mb"] > 10 and v["cpu"] >= 0
    assert v["listen_until"] > now_ms() and v["nav_until"] > now_ms(), "the listening windows"
    assert v["camera"] == {"on": True, "state": "present", "why": "", "released": False, "contact": True, "faces": 1}
    assert v["capture"]["frames"] == 7 and v["brain"] == {"model": "m/x", "online": True}
    off, _ = Bus.vitals(_bus(_presence_obj=None, paused_until=now_ms() + 60_000), None)
    assert off["camera"]["on"] is False and off["mic"]["paused"] and off["capture"]["paused"]


def test_status_by_voice():
    for q in ("how much ram are you using", "are you updating", "show your status", "what version are you"):
        assert "show_status" in {t["function"]["name"] for t in agent.select_tools(q)}, q


def test_the_dock_is_wired_end_to_end():
    ov = ROOT / "overlay"
    pre = (ov / "preload.cjs").read_text(encoding="utf-8")
    assert all(k in pre for k in ("updateState", "updateCheck", "updateNow"))
    main = (ov / "main.cjs").read_text(encoding="utf-8")
    assert 'ipcMain.on("update-check"' in main and 'ipcMain.on("update-now"' in main and "state: setUpdate" in main
    assert 'event.type === "vitals"' in main and "getAppMetrics" in main, "the overlay's own load is added"
    assert "setTimeout(check, 2 * 60 * 1000)" in main
    upd = (ov / "updater.cjs").read_text(encoding="utf-8")
    for phase in ("checking", "uptodate", "downloading", "ready", "off", "error"):
        assert f'phase: "{phase}"' in upd, phase
    app = (ov / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "<Signals" in app and "<Dock" in app and 'ev.type === "dock"' in app
    bus = (ROOT / "ambient" / "bus.py").read_text(encoding="utf-8")
    assert 'target=self._vitals_loop' in bus and '"vitals": self._vitals_line' in bus


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} checks passed")
