"""D67: a diagnostic report anyone can make and send, so a problem on someone else's PC can be fixed.

"Jimmy, make a diagnostic report", the Status dock's Report button, `python -m ambient report`,
or Claude Desktop through `python -m jimmy mcp` (the `diagnostic_report` tool). One Markdown file
in <data>/reports/, opened in Explorer. Sending it is the user's act: "send it to the developer"
opens a prefilled GitHub issue they read and submit themselves, with the file to attach. Nothing
is ever sent on its own.

What's in it: versions, Windows, settings (keys only as present/absent), Jimmy's live status, the
camera checks (D65), which apps Windows says hold the camera and mic, cameras and GPU, Jimmy's
processes, and the end of Jimmy's own log (which never holds captured text: D45). What's not:
anything Jimmy captured, keys, your user name (replaced by <you>).
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from . import config

REPO = "Adhrit-Verma/Jimmy"
_HIDE = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW: never a flashing console


def status_file() -> Path:
    return config.DATA_DIR / "logs" / "status.json"


def _ps(cmd: str, timeout: float = 15) -> str:
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                              text=True, timeout=timeout, creationflags=_HIDE).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "(couldn't ask Windows)"


def _mask(text: str) -> str:
    user = os.environ.get("USERNAME") or ""
    home = str(Path.home())
    text = text.replace(home, "<home>").replace(home.replace("\\", "\\\\"), "<home>")
    return text.replace(user, "<you>") if len(user) >= 3 else text


def _version() -> str:
    from jimmy import install
    try:
        if install.INSTALLED:
            return json.loads(install.MARKER.read_text(encoding="utf-8")).get("version", "?") + " (installed)"
        return json.loads((install.ROOT / "overlay" / "package.json").read_text(encoding="utf-8"))["version"] + " (dev)"
    except (OSError, ValueError, KeyError):
        return "?"


def _tail(path: Path, n: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return "(none)"


def build(bus=None) -> str:
    """The report, as Markdown. `bus`: the running Jimmy, for live state; else status.json."""
    from jimmy import install

    from . import selfcheck
    from .audio import _alive, _holders, _running_images, app_label  # noqa: F401
    out = [f"# Jimmy diagnostic report, {time.strftime('%Y-%m-%d %H:%M')}", "",
           "No captured screens, speech or keys are in this file; your user name is replaced by <you>.", ""]
    add = out.append

    add("## Jimmy and this PC")
    add(f"- Jimmy {_version()}, Python {platform.python_version()}, {platform.platform()}")
    add(f"- Data folder: {config.DATA_DIR}")
    try:
        import shutil
        add(f"- Free on that drive: {shutil.disk_usage(config.DATA_DIR).free / 1e9:.1f} GB")
    except OSError:
        pass
    s = install.settings() if install.SETTINGS.exists() else {}
    add(f"- Settings: {json.dumps(s, sort_keys=True) if s else '(a development copy: none)'}")
    try:
        keys = sorted(install.secrets().keys())
    except Exception:
        keys = []
    add(f"- Keys present: {', '.join(keys) or 'none in Jimmy (maybe in the environment)'}")

    add("")
    add("## Live status")
    live = None
    if bus is not None:
        try:
            live, _ = bus.vitals(None)
        except Exception as exc:
            add(f"- (couldn't read it: {type(exc).__name__})")
    else:
        try:
            st = json.loads(status_file().read_text(encoding="utf-8"))
            age = time.time() - st.get("_written", 0)
            live = st
            add(f"- From the running Jimmy, {age:.0f} s ago" if age < 120 else
                f"- Jimmy isn't running (last status {age / 60:.0f} min ago)")
        except (OSError, ValueError):
            add("- Jimmy isn't running (no status saved)")
    if live:
        for k in ("cpu", "ram_mb", "mic", "camera", "capture", "brain"):
            add(f"- {k}: {json.dumps(live.get(k))}")

    add("")
    add("## Camera")

    class _NoBus:
        _presence, _presence_obj = (live or {}).get("camera") or None, None
    for f in selfcheck.camera(bus if bus is not None else _NoBus()):
        add(f"- {'ok ' if f['ok'] else 'BAD'} {f['check']}: {f['say']}")
    images = _running_images()
    for cap in ("webcam", "microphone"):                # every app Windows marks as using it, alive or not
        add(f"- Windows says using the {cap}: " + (", ".join(
            f"{app_label(k)} ({'running' if _alive(k, images) else 'NOT running: stale'})"
            for k, _ in _holders(cap, alive_only=False)) or "nobody"))
    add("- Cameras: " + (_ps("Get-PnpDevice -Class Camera,Image -PresentOnly | % { $_.FriendlyName + ' [' + $_.Status + ']' }")
                         .replace("\n", "; ") or "none found"))

    add("")
    add("## Jimmy's processes")
    add("```")
    add(_ps("Get-Process | ? { $_.Path -and ($_.Path -like '*Jimmy*' -or $_.Path -like '" + str(config.DATA_DIR)
            + "*') } | % { '{0,-14} {1,6} MB  {2}' -f $_.Name, [int]($_.WorkingSet64/1MB), $_.Path }") or "(none)")
    add("```")
    gpu = _ps("if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { nvidia-smi --query-gpu=name,driver_version,"
              "memory.used,memory.total --format=csv,noheader }")
    if gpu and "couldn't" not in gpu:
        add(f"- GPU: {gpu}")

    add("")
    add("## The end of Jimmy's log")
    add("```")
    add(_tail(config.DATA_DIR / "logs" / "jimmy.log", 150))
    add("```")
    crash = config.DATA_DIR / "logs" / "crash.log"
    if crash.exists() and crash.stat().st_size:
        add("")
        add("## Hard crashes (crash.log)")
        add("```")
        add(_tail(crash, 60))
        add("```")
    if install.INSTALLED:
        add("")
        add("## The launcher's log")
        add("```")
        add(_tail(install.ROOT.parent.parent / "setup.log", 40))
        add("```")
    return _mask("\n".join(out)) + "\n"


def save(bus=None) -> Path:
    d = config.DATA_DIR / "reports"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"jimmy-report-{time.strftime('%Y%m%d-%H%M%S')}.md"
    p.write_text(build(bus), encoding="utf-8")
    return p


def issue_url(path: Path) -> str:
    """A GitHub issue, prefilled with the report's first part; the user reads it, attaches the file
    and submits it themselves."""
    text = path.read_text(encoding="utf-8")
    head = text.split("## Jimmy's processes")[0][:3500]
    body = (f"**What happened** (please write a line):\n\n\n**Report** (the full file is `{path.name}`: "
            f"drag it into this box)\n\n{head}")
    return f"https://github.com/{REPO}/issues/new?title={quote('Diagnostic report: ' + _version())}&body={quote(body)}"


def write_status(v: dict) -> None:
    """The running Jimmy's latest vitals, for a report made outside it (the CLI, Claude Desktop)."""
    try:
        status_file().parent.mkdir(parents=True, exist_ok=True)
        status_file().write_text(json.dumps({**v, "_written": time.time()}), encoding="utf-8")
    except OSError:
        pass


def show(path: Path) -> None:
    """Open Explorer with the report selected."""
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)], creationflags=_HIDE)


def claude_config() -> dict:
    """D67: the entry for Claude Desktop's claude_desktop_config.json, with this copy's real paths."""
    from jimmy import install
    py = (config.DATA_DIR / "runtime" / "venv" / "Scripts" / "python.exe") if install.INSTALLED else Path(sys.executable)
    return {"mcpServers": {"jimmy": {"command": str(py), "args": ["-m", "jimmy", "mcp"],
                                     "env": {"PYTHONPATH": str(install.ROOT)}}}}


if __name__ == "__main__":
    if "--claude" in sys.argv:
        print(json.dumps(claude_config(), indent=2))
        sys.exit(0)
    p = save()
    print(p)
    if "--open" in sys.argv:
        show(p)
