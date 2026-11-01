"""What the onboarding asks of Jimmy's own Python, once it's installed (D61).

`python -m ambient.setup <step>`, each printing JSON lines the onboarding reads:

- `verify`  import every native piece (OpenCV, ONNX Runtime, CTranslate2, Whisper, UI
            Automation, WASAPI, screen capture) and say where the C++ runtime was loaded
            from (Jimmy's own folder, not System32) and whether CUDA works.
- `models --whisper NAME`  download the Whisper model into the data folder (HF_HOME),
            with progress: {"step": "model", "done": bytes, "total": bytes}.
- `keys`    read {"NAME": "value", ...} from stdin (never argv: argv shows in process lists)
            and store them DPAPI-encrypted.
- `settings` read {...} from stdin and save it as the user's settings.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path


def say(**kw) -> None:
    print(json.dumps(kw), flush=True)


def _loaded_from(dll: str) -> str | None:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    h = k32.GetModuleHandleW(dll)
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    k32.GetModuleFileNameW(wintypes.HMODULE(h), buf, 1024)
    return buf.value


def verify() -> int:
    import importlib
    from jimmy import install  # noqa: F401  (registers CUDA DLL folders, like a real start)
    failed = 0
    for mod in ("numpy", "cv2", "onnxruntime", "ctranslate2", "faster_whisper", "uiautomation",
                "pyaudiowpatch", "windows_capture", "webrtcvad", "httpx", "PIL"):
        t = time.perf_counter()
        try:
            importlib.import_module(mod)
            say(step="verify", module=mod, ok=True, ms=int(1000 * (time.perf_counter() - t)))
        except Exception as exc:
            failed += 1
            say(step="verify", module=mod, ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
    for dll in ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        say(step="verify", dll=dll, path=_loaded_from(dll))
    try:
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        say(step="verify", cuda_devices=n, cuda_dirs=install.cuda_dirs())
    except Exception as exc:
        say(step="verify", cuda_devices=0, error=str(exc)[:200])
    say(step="verify", done=True, failed=failed)
    return 1 if failed else 0


def models(whisper: str) -> int:
    from faster_whisper.utils import _MODELS
    from huggingface_hub import HfApi, snapshot_download
    repo = _MODELS.get(whisper, whisper)
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        total = sum((s.size or 0) for s in info.siblings)
    except Exception:
        total = 0
    import os
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / ("models--" + repo.replace("/", "--"))
    result: dict = {}

    def go():
        try:
            result["path"] = snapshot_download(repo, allow_patterns=["config.json", "preprocessor_config.json",
                                                                    "model.bin", "tokenizer.json", "vocabulary.*"])
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    th = threading.Thread(target=go, daemon=True)
    th.start()
    from .storage import _size
    while th.is_alive():
        say(step="model", name=whisper, done=_size(cache), total=total)
        th.join(0.7)
    if "error" in result:
        say(step="model", name=whisper, ok=False, error=result["error"])
        return 1
    say(step="model", name=whisper, ok=True, done=_size(cache), total=total, path=result["path"])
    return 0


def keys() -> int:
    from jimmy import install
    got = json.loads(sys.stdin.read() or "{}")
    for name, value in got.items():
        if name in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY"):
            install.set_secret(name, str(value or ""))
    say(step="keys", ok=True, saved=sorted(k for k, v in got.items() if v))
    return 0


def settings() -> int:
    from jimmy import install
    saved = install.save_settings(json.loads(sys.stdin.read() or "{}"))
    say(step="settings", ok=True, settings=saved)
    return 0


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m ambient.setup")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("verify")
    m = sub.add_parser("models")
    m.add_argument("--whisper", default="small")
    sub.add_parser("keys")
    sub.add_parser("settings")
    a = ap.parse_args(argv)
    return {"verify": verify, "keys": keys, "settings": settings}.get(a.step, lambda: models(a.whisper))()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
