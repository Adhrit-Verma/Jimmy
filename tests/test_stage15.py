"""One runnable check for D60-D62: an installed Jimmy (data folder, settings, keys, storage
limits) and the setup's pieces. `python tests/test_stage15.py`. No network; each check that
needs an "installed" copy runs in a subprocess with its own temp folders."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _py(code: str, env: dict, cwd: Path = ROOT) -> str:
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(cwd),
                         env={**os.environ, "PYTHONPATH": str(cwd), **env})
    assert out.returncode == 0, out.stderr[-800:]
    return out.stdout.strip()


def _copy_code(dst: Path, installed: bool) -> Path:
    """A copy of jimmy/ (and ambient/config.py's package) as an 'installed' or dev tree."""
    import shutil
    for name in ("jimmy", "ambient"):
        shutil.copytree(ROOT / name, dst / name, ignore=shutil.ignore_patterns("__pycache__"))
    if installed:
        (dst / "jimmy-installed.json").write_text("{}", encoding="utf-8")
    return dst


def test_d59_installed_copy_follows_the_pointer_dev_copy_never_does():
    t = Path(tempfile.mkdtemp())
    appdata, data = t / "appdata", t / "D_JimmyData"
    (appdata / "Jimmy").mkdir(parents=True)
    (appdata / "Jimmy" / "location.json").write_text(json.dumps({"data": str(data)}), encoding="utf-8")
    env = {"APPDATA": str(appdata), "JIMMY_DATA": "", "JIMMY_AMBIENT_DATA": ""}
    env = {k: v for k, v in env.items() if v} | {"APPDATA": str(appdata)}
    os.environ.pop("JIMMY_DATA", None)
    code = ("from jimmy import install, config as j; from ambient import config as a; "
            "print(install.INSTALLED, j.DATA_DIR, a.DATA_DIR, j.MEMORY_DB.parent == a.DATA_DIR)")
    inst = _py(code, env, _copy_code(t / "inst", installed=True)).split()
    assert inst[0] == "True" and Path(inst[1]) == data and Path(inst[2]) == data and inst[3] == "True", inst
    dev = _py(code, env, _copy_code(t / "dev", installed=False)).split()
    assert dev[0] == "False" and Path(dev[1]) == t / "dev" / "data", "a dev checkout never follows the pointer"
    print("ok  D60: an installed copy keeps its data where the user chose; a dev checkout ignores that")


def test_d59_settings_apply_over_the_defaults_and_caches_stay_off_c():
    t = Path(tempfile.mkdtemp())
    data = t / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"profile": "lite", "whisper_model": "small", "whisper_device": "cpu",
                                                     "webcam": False, "local_ai": False, "retention_days": 7,
                                                     "storage_cap_gb": 5, "provider": "gemini"}), encoding="utf-8")
    code = ("import os; from ambient import config as a; from jimmy import config as j; "
            "print(a.WHISPER_MODEL, a.WHISPER_DEVICE, a.WHISPER_FALLBACK_MODEL, a.PRESENCE, a.INDEX_EVERY_S, "
            "a.RETENTION_DAYS, a.STORAGE_CAP_GB, j.PROVIDER, os.environ['HF_HOME'].startswith(os.environ['JIMMY_DATA']))")
    out = _py(code, {"JIMMY_DATA": str(data), "JIMMY_PROVIDER": ""}, _copy_code(t / "inst", installed=True)).split()
    assert out == ["small", "cpu", "base", "False", "0", "7", "5.0", "gemini", "True"], out
    print("ok  D60: the user's profile, limits and provider apply; model caches go to the data folder")


def test_d59_keys_are_encrypted_and_found():
    t = Path(tempfile.mkdtemp())
    code = ("from jimmy import install; install.set_secret('GEMINI_API_KEY', 'sekrit-123'); "
            "from jimmy.llm import api_key; print(api_key('GEMINI_API_KEY'), b'sekrit' in install.SECRETS.read_bytes())")
    env = {"JIMMY_DATA": str(t), "GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}
    root = _copy_code(t / "inst", installed=True)
    # The registry may hold a real key on this PC: keep it out by naming a variable no one has.
    out = _py(code.replace("GEMINI_API_KEY", "JIMMY_TEST_KEY"), {k: v for k, v in env.items() if v} | {"JIMMY_DATA": str(t)}, root)
    assert out == "sekrit-123 False", out
    print("ok  D60: keys typed in setup are DPAPI-encrypted on disk and found by api_key")


def test_d59_storage_limits_delete_oldest_days_never_today():
    from ambient import config, storage
    from ambient.db import Store
    d = Path(tempfile.mkdtemp())
    real = config.DATA_DIR
    config.DATA_DIR = d
    try:
        s = Store(str(d / "ambient.db"))
        now = int(time.time() * 1000)
        w = s.open_window(kind="app", ts=now - 50 * storage.DAY_MS)
        for age in (50, 20, 3, 0):
            s.add_frame(w, "app", "t", None, 0, now - age * storage.DAY_MS, None)
        assert storage.enforce(s, now, days=0, cap_gb=0)["frames"] == 0, "no limits: nothing goes"
        storage.enforce(s, now, days=10, cap_gb=0)
        with s._lock:
            n = s.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        assert n == 2, n
        storage.enforce(s, now, days=0, cap_gb=1e-12)
        with s._lock:
            ages = [round((now - r[0]) / storage.DAY_MS) for r in s.conn.execute("SELECT ts FROM frames")]
        assert ages == [0], ages
        assert set(storage.usage()["bytes"]) >= {"captures", "thumbnails", "models", "cache", "logs", "total"}
    finally:
        config.DATA_DIR = real
    print("ok  D60: retention and the size cap delete whole old days first, never today")


def test_d59_settings_api_returns_what_changed():
    import urllib.request
    from ambient.api import OverlayAPI
    seen = {}

    def change(body):
        seen.update(body)
        return {"settings": {"retention_days": body["changes"]["retention_days"]}, "restart": False}
    api = OverlayAPI({"state": lambda: {"paused": False}, "pause": lambda m, **k: None, "resume": lambda **k: None,
                      "dismiss": lambda i: None, "post_settings": change,
                      "get_storage": lambda p: {"bytes": {"total": 1}}}).start()
    try:
        def call(path, body=None):
            req = urllib.request.Request(api.url + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {api.token}", "Content-Type": "application/json"},
                                         method="POST" if body is not None else "GET")
            return json.loads(urllib.request.urlopen(req, timeout=5).read())
        r = call("/settings", {"changes": {"retention_days": 14}})
        assert r == {"settings": {"retention_days": 14}, "restart": False}, r
        assert call("/storage") == {"bytes": {"total": 1}}
    finally:
        api.stop()
    print("ok  D60: Settings' POST gets its result back, not the overlay state")


def test_d60_setup_pieces_are_in_place():
    lock = (ROOT / "installer" / "build.py").read_text(encoding="utf-8")
    assert "--require-hashes" in (ROOT / "overlay" / "launcher.cjs").read_text(encoding="utf-8"), "packages by hash"
    assert "UV_SHA256" in lock and "msvcp140.dll" in lock, "uv pinned; the C++ runtime app-local"
    nsh = (ROOT / "overlay" / "build" / "installer.nsh").read_text(encoding="utf-8")
    assert "${ifNot} ${isUpdated}" in nsh, "an update must not undo the setup"
    pkg = json.loads((ROOT / "overlay" / "package.json").read_text(encoding="utf-8"))["build"]["nsis"]
    assert pkg["perMachine"] is False and pkg["allowToChangeInstallationDirectory"] and pkg["oneClick"] is False
    launcher = (ROOT / "overlay" / "launcher.cjs").read_text(encoding="utf-8")
    assert 'app.setPath("userData"' in launcher and 'app.setPath("userData"' in (ROOT / "overlay" / "main.cjs").read_text(encoding="utf-8")
    print("ok  D61: hashes, a pinned uv, app-local C++ runtime, per-user setup, update-safe uninstall, caches off C:")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
