"""The console, kept (D45): everything `ambient run` prints also goes to
data/logs/jimmy.log, rotated (5 files x 2 MB), one timestamp per line.

On 2026-10-05 the console held the only record of why a task failed, why a line
was refused ("Discord has the mic") and what resumed a pause, and it was gone
with the window. The log keeps the shape of what happened, not what was on
screen or said: text in quotes (what was heard, control names, a model's reply)
and card lines are cut to their length, and anything shaped like an API key is
scrubbed. data/ is git-ignored; "forget a span" deletes captures, and the log
holds none of their text.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

LOG_DIR = config.DATA_DIR / "logs"
MAX_BYTES, BACKUPS = 2_000_000, 4          # 5 files in all

# '…' / "…" / “…” / ‘…’ (Python reprs print either quote), longer than a short word.
_QUOTED = re.compile(r"'(?:[^'\\\n]|\\.){3,}'|\"(?:[^\"\\\n]|\\.){3,}\"|“[^”\n]{3,}”|‘[^’\n]{3,}’")
_CARD = re.compile(r"^(\s*\[card\] [A-Z]+(?: muted here)?: )(.+?)(\s+\(.*\))?$")
_GATE = re.compile(r"^(\s*\[gate\] \w+ candidate )\((.*?)\)( -> .*)?$")     # the reason names words seen
_KEYS = re.compile(r"\b(?:nvapi-|sk-|sk_)[A-Za-z0-9_\-]{8,}|\bBearer\s+\S+", re.I)


def redact(line: str) -> str:
    """A console line as the log keeps it: no captured text, no keys."""
    line = _KEYS.sub("<key>", line)
    m = _CARD.match(line)
    if m:
        line = f"{m[1]}<{len(m[2])} chars>"
    m = _GATE.match(line)
    if m:
        line = f"{m[1]}(<{len(m[2])} chars>){m[3] or ''}"
    return _QUOTED.sub(lambda q: f"<{len(q[0]) - 2} chars>", line)


class _Tee:
    """A text stream that writes through to the real one and logs whole lines."""

    def __init__(self, real, log: logging.Logger, level: int):
        self.real, self.log, self.level = real, log, level
        self._buf, self._lock = "", threading.Lock()

    def write(self, s: str) -> int:
        try:
            n = self.real.write(s)
        except Exception:
            n = len(s)
        with self._lock:
            self._buf += s
            *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            if ln.strip():
                try:
                    self.log.log(self.level, redact(ln.rstrip()))
                except Exception:
                    pass
        return n if isinstance(n, int) else len(s)

    def flush(self) -> None:
        try:
            self.real.flush()
        except Exception:
            pass

    def __getattr__(self, name):                 # encoding, isatty, fileno… from the real stream
        return getattr(self.real, name)


def install(log_dir: Path | None = None) -> Path:
    """Tee stdout and stderr into the rotating log. Returns its path."""
    d = Path(log_dir or LOG_DIR)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "jimmy.log"
    log = logging.getLogger("jimmy.console")
    log.setLevel(logging.INFO)
    log.propagate = False
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        h = RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname).1s %(message)s"))
        log.addHandler(h)
    if not isinstance(sys.stdout, _Tee):
        sys.stdout = _Tee(sys.stdout, log, logging.INFO)
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, log, logging.WARNING)
    return path
