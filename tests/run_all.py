"""Every offline suite, in parallel; non-zero exit if any fails (CI gates releases on this, D68).

    .venv\\Scripts\\python.exe tests\\run_all.py
"""
from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = sorted(HERE.glob("test_*.py"))


def run(path: Path) -> tuple[str, int, str]:
    p = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=HERE.parent, timeout=900)
    return path.name, p.returncode, (p.stdout + p.stderr)[-1500:]


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(run, SUITES))
    for name, code, tail in results:
        print(f"{'ok  ' if code == 0 else 'FAIL'} {name}")
        if code:
            print(tail)
    failed = [n for n, c, _ in results if c]
    print(f"\n{len(results) - len(failed)}/{len(results)} suites passed")
    sys.exit(1 if failed else 0)
