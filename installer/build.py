"""Build Jimmy-Setup.exe (D61). `python installer/build.py [--skip-builder]`.

1. uv (pinned, SHA-256 checked): it ships inside Jimmy and installs Jimmy's Python on the
   user's PC. Here it also locks the packages.
2. Lock files with hashes for Windows x64 / Python 3.12: requirements.lock (everyone) and
   requirements-gpu.lock (cuBLAS, only on PCs with an NVIDIA GPU). Installed with
   --require-hashes: a package that doesn't match its hash is refused.
3. Stage Jimmy's Python code with `jimmy-installed.json` (the marker that makes an installed
   copy use the data folder the user chose, jimmy/install.py).
4. The Visual C++ runtime DLLs (>= 14.40, onnxruntime's need), carried app-locally next
   to Jimmy's Python: no admin, nothing written to System32.
5. The icon and installer art from installer/art.py; the overlay (vite build).
6. electron-builder: an NSIS installer, per user (no admin), any folder on any drive.

Needs Node/npm and internet. Output: installer/out/Jimmy-Setup-<version>.exe.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STAGE = HERE / "stage"
# D64: one version, overlay/package.json's. A new one there is what makes CI publish a release.
VERSION = json.loads((ROOT / "overlay" / "package.json").read_text(encoding="utf-8"))["version"]
UV_VERSION = "0.13.6"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
UV_SHA256 = "a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f"
PYTHON = "3.12.10"
VCRT = ["msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll", "vcomp140.dll"]
CODE = ["ambient", "jimmy"]
MODELS = ["face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"]


def step(msg: str) -> None:
    print(f"\n== {msg}", flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_uv() -> Path:
    tools = STAGE / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    exe = tools / "uv.exe"
    if exe.exists():
        return exe
    z = HERE / "cache" / f"uv-{UV_VERSION}.zip"
    z.parent.mkdir(exist_ok=True)
    if not z.exists():
        urllib.request.urlretrieve(UV_URL, z)
    if sha256(z) != UV_SHA256:
        z.unlink()
        sys.exit("uv download doesn't match its SHA-256: refusing to ship it")
    with zipfile.ZipFile(z) as zf:
        for name in ("uv.exe", "uvw.exe"):
            with zf.open(name) as src, open(tools / name, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return exe


def lock(uv: Path) -> None:
    out = STAGE / "jimmy"
    out.mkdir(parents=True, exist_ok=True)
    common = ["--python-version", "3.12", "--python-platform", "x86_64-pc-windows-msvc", "--generate-hashes",
              "--no-header", "--quiet"]
    subprocess.run([str(uv), "pip", "compile", str(ROOT / "requirements.txt"), *common,
                    "-o", str(out / "requirements.lock")], check=True)
    gpu_in = HERE / "cache" / "requirements-gpu.in"
    gpu_in.write_text("nvidia-cublas-cu12>=12.4,<13\n", encoding="utf-8")
    subprocess.run([str(uv), "pip", "compile", str(gpu_in), *common, "-o", str(out / "requirements-gpu.lock")],
                   check=True)


def stage_code() -> None:
    dst = STAGE / "jimmy"
    for name in CODE:
        shutil.rmtree(dst / name, ignore_errors=True)
        shutil.copytree(ROOT / name, dst / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dst / "models").mkdir(exist_ok=True)
    for m in MODELS:
        shutil.copy2(ROOT / "models" / m, dst / "models" / m)
    for f in ("LICENSE", "README.md"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, dst / f)
    (dst / "jimmy-installed.json").write_text(json.dumps(
        {"version": VERSION, "python": PYTHON, "uv": UV_VERSION}, indent=1), encoding="utf-8")


def stage_vcrt() -> None:
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    dst = STAGE / "tools" / "vcrt"
    dst.mkdir(parents=True, exist_ok=True)
    ver = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-Item '{sys32 / 'msvcp140.dll'}').VersionInfo.ProductVersion"],
                         capture_output=True, text=True).stdout.strip()
    major_minor = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0, 0)
    if major_minor < (14, 40):
        sys.exit(f"this PC's msvcp140.dll is {ver}; onnxruntime needs >= 14.40. Install the latest "
                 "VC++ redistributable on the build PC first.")
    for name in VCRT:
        if (sys32 / name).exists():
            shutil.copy2(sys32 / name, dst / name)
    (dst / "version.txt").write_text(ver, encoding="utf-8")


def build_overlay(skip_builder: bool) -> None:
    ov = ROOT / "overlay"
    npm = "npm.cmd" if os.name == "nt" else "npm"
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    subprocess.run([npm, "run", "build"], cwd=ov, check=True, env=env)
    if skip_builder:
        return
    subprocess.run(["npx.cmd" if os.name == "nt" else "npx", "electron-builder", "--win", "nsis", "--x64",
                    "--publish", "never"], cwd=ov, check=True, env=env)


def main() -> int:
    skip = "--skip-builder" in sys.argv
    step(f"uv {UV_VERSION}")
    uv = fetch_uv()
    step("lock files (hashes, Windows x64, Python 3.12)")
    lock(uv)
    step("Jimmy's code")
    stage_code()
    step("Visual C++ runtime (app-local)")
    stage_vcrt()
    step("icon and installer art")
    subprocess.run([sys.executable, str(HERE / "art.py")], check=True)
    step("overlay" + ("" if skip else " + installer"))
    build_overlay(skip)
    out = sorted((HERE / "out").glob("Jimmy-Setup-*.exe"))
    for exe in out:
        print(f"\n{exe}  {exe.stat().st_size / 1e6:.0f} MB  sha256 {sha256(exe)}")
        (exe.with_suffix(".exe.sha256")).write_text(f"{sha256(exe)}  {exe.name}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
