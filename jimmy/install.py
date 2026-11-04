"""An installed Jimmy (D60): where its data lives, the user's settings, encrypted keys.

Stdlib only: `jimmy/config.py` imports this first, before anything heavy.

- **Installed or not.** The setup puts `jimmy-installed.json` next to the code. Only then
  does `%APPDATA%\\Jimmy\\location.json` (the one small file Jimmy keeps on C:) say where the
  data folder is. A development checkout ignores it and keeps `<repo>\\data`, so testing an
  install on this PC can't move the developer's data.
- **Settings** (`<data>\\settings.json`): what the user chose in onboarding and in Settings
  (profile, retention, storage cap...). `ambient/config.py` applies them over its defaults.
- **Keys** (`<data>\\secrets.bin`): the API keys typed in onboarding, encrypted with Windows
  DPAPI (only this Windows user can read them). Read by `jimmy.llm.api_key` after the
  environment, the registry and `.env`.
- **Off C:.** Model and download caches default to the data folder (Hugging Face, Ollama, uv).
- **CUDA.** `nvidia-cublas-cu12` puts its DLLs in `site-packages/nvidia/*/bin`, which Windows
  never searches; they're registered before ctranslate2 loads.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# D67: Media Foundation opens the webcam in ~1 s without its hardware transforms, ~17 s (over a
# minute in an installed copy) with them. OpenCV reads this once, when it loads, so it has to be
# set before any module imports cv2; this module is imported first by every entry point.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / "jimmy-installed.json"
INSTALLED = MARKER.exists()
POINTER = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Jimmy" / "location.json"


def read_pointer() -> Path | None:
    try:
        d = json.loads(POINTER.read_text(encoding="utf-8")).get("data")
        return Path(d) if d else None
    except (OSError, ValueError, AttributeError):
        return None


def write_pointer(data: Path) -> None:
    POINTER.parent.mkdir(parents=True, exist_ok=True)
    tmp = POINTER.with_suffix(".tmp")
    tmp.write_text(json.dumps({"data": str(Path(data).resolve()), "app": str(ROOT)}, indent=1), encoding="utf-8")
    tmp.replace(POINTER)


def data_dir() -> Path:
    """JIMMY_DATA, else (installed) the pointer, else the repo's own data folder."""
    env = os.environ.get("JIMMY_DATA")
    if env:
        return Path(env)
    if INSTALLED:
        return read_pointer() or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Jimmy" / "data"
    return ROOT / "data"


DATA = data_dir()
SETTINGS = DATA / "settings.json"
SECRETS = DATA / "secrets.bin"


# --- settings -------------------------------------------------------------------------------
DEFAULTS = {"profile": "balanced", "retention_days": 30, "storage_cap_gb": 20, "webcam": True,
            "local_ai": False, "voice": "sapi", "start_with_windows": True, "gpu_release_away_s": 600,
            "provider": "", "whisper_model": "", "whisper_device": "",   # "" = the code's default
            "auto_update": True, "camera_index": 0}                    # D64: the overlay's updater reads it


def settings() -> dict:
    try:
        got = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return {**DEFAULTS, **(got if isinstance(got, dict) else {})}
    except (OSError, ValueError):
        return dict(DEFAULTS)


def save_settings(changes: dict) -> dict:
    """Merge `changes` (known keys only) into settings.json, atomically. Returns the result."""
    cur = settings()
    cur.update({k: v for k, v in changes.items() if k in DEFAULTS})
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1), encoding="utf-8")
    tmp.replace(SETTINGS)
    return cur


# --- keys, DPAPI-encrypted ------------------------------------------------------------------
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), buf), Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = (fn(ctypes.byref(src), "Jimmy: keys", None, None, None, 1, ctypes.byref(out)) if protect
          else fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out)))
    if not ok:
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def secrets() -> dict:
    try:
        return json.loads(_dpapi(SECRETS.read_bytes(), protect=False).decode("utf-8"))
    except Exception:
        return {}


def set_secret(name: str, value: str | None) -> None:
    """Store (or, with None/"", remove) one key. Never printed, never logged."""
    cur = secrets()
    if value:
        cur[name] = value.strip()
    else:
        cur.pop(name, None)
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    SECRETS.write_bytes(_dpapi(json.dumps(cur).encode("utf-8"), protect=True))


# --- off C:, and CUDA --------------------------------------------------------------------------
def prepare_environment() -> None:
    """Installed: caches go to the data folder. Any copy: CUDA DLLs from pip are findable."""
    if os.name == "nt" and Path(sys.executable).name.lower() == "pythonw.exe":
        hide_consoles()
    if INSTALLED:
        os.environ.setdefault("HF_HOME", str(DATA / "models" / "hf"))
        os.environ.setdefault("OLLAMA_MODELS", str(DATA / "models" / "ollama"))
        os.environ.setdefault("UV_CACHE_DIR", str(DATA / "cache" / "uv"))
    cuda_dirs()


def hide_consoles() -> None:
    """D65: pythonw has no console, so every console program started under it (by Jimmy or
    by a library) opens a new, visible window: the user saw command prompts flash across the
    screen at start. CREATE_NO_WINDOW gives each one a hidden console instead, which its own
    children share."""
    import subprocess
    if getattr(subprocess.Popen, "_jimmy_hidden", False):
        return
    init = subprocess.Popen.__init__

    def hidden(self, *args, creationflags: int = 0, **kwargs):
        init(self, *args, creationflags=creationflags | 0x08000000, **kwargs)   # CREATE_NO_WINDOW
    subprocess.Popen.__init__ = hidden
    subprocess.Popen._jimmy_hidden = True


def cuda_dirs() -> list[str]:
    """Register site-packages/nvidia/*/bin (cuBLAS from `nvidia-cublas-cu12`) for DLL loading:
    both os.add_dll_directory and PATH, because ctranslate2 also searches PATH."""
    found = []
    for base in (Path(p) for p in sys.path if p and p.endswith("site-packages")):
        nv = base / "nvidia"
        if not nv.is_dir():
            continue
        for b in sorted(nv.glob("*/bin")):
            found.append(str(b))
    for d in found:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    if found:
        os.environ["PATH"] = os.pathsep.join(found + [os.environ.get("PATH", "")])
    return found


if __name__ == "__main__":
    import tempfile
    probe = Path(tempfile.mkdtemp()) / "secrets.bin"
    SECRETS = probe
    set_secret("TEST_KEY", "abc123")
    assert secrets() == {"TEST_KEY": "abc123"} and b"abc123" not in probe.read_bytes(), "encrypted on disk"
    set_secret("TEST_KEY", None)
    assert secrets() == {}
    print("install.py self-check ok; installed:", INSTALLED, "| data:", DATA)
