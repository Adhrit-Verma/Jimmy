"""D70: apply a small update (a patch) to an installed Jimmy, instead of the 170 MB setup.

Most releases change only Jimmy's own code: the overlay's app.asar (under 1 MB) and the Python
in resources/jimmy (under 1 MB). Electron, uv, the C++ runtime and the face models, the other
170 MB, are the same; `base` in jimmy-installed.json fingerprints them, and the updater only
picks a patch built on the same base (overlay/updater.cjs).

Run by Jimmy's own pythonw, detached, after Jimmy.exe has been told to quit:

    pythonw patch.py <patch.zip> <install folder>

Stdlib only, and it never imports Jimmy's code (it is replacing it). It waits for Jimmy.exe to
let go of app.asar, puts the new files in place, and starts Jimmy again; if anything fails, the
old app.asar goes back and Jimmy starts as it was.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def apply(patch: Path, install: Path, wait_s: float = 40) -> str:
    """Put the patch in place. Returns "" or what went wrong. Only `app.asar` and `jimmy/...`
    are ever written, inside <install>/resources (a zip can't name anything else)."""
    res = install / "resources"
    asar, old = res / "app.asar", res / "app.asar.old"
    with zipfile.ZipFile(patch) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        bad = [n for n in names if not (n == "app.asar" or n.startswith("jimmy/")) or ".." in n or ":" in n
               or n.startswith(("/", "\\"))]
        if bad or "app.asar" not in names:
            return f"not a Jimmy patch: {bad[:3] or 'no app.asar'}"
        deadline = time.time() + wait_s
        while True:                              # Jimmy.exe holds app.asar open until it has quit
            try:
                old.unlink(missing_ok=True)
                asar.rename(old)
                break
            except OSError as exc:
                if time.time() > deadline:
                    return f"Jimmy didn't close: {exc}"
                time.sleep(0.5)
        try:
            for n in names:
                dest = res / n
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
        except OSError as exc:
            asar.unlink(missing_ok=True)
            old.rename(asar)                     # as it was
            return f"couldn't write {n}: {exc}"
    old.unlink(missing_ok=True)
    return ""


if __name__ == "__main__":
    patch, install = Path(sys.argv[1]), Path(sys.argv[2])
    problem = apply(patch, install)
    try:
        with open(install / "setup.log", "a", encoding="utf-8") as log:
            log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} patch {patch.name}: {problem or 'applied'}\n")
    except OSError:
        pass
    env = {k: v for k, v in os.environ.items() if not k.startswith("JIMMY_OVERLAY_")}   # so it's the launcher
    subprocess.Popen([str(install / "Jimmy.exe")], env=env, cwd=str(install),
                     creationflags=0x00000008 | 0x00000200)      # DETACHED_PROCESS | NEW_PROCESS_GROUP
    sys.exit(1 if problem else 0)
