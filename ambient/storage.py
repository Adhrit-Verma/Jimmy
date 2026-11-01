"""Storage the user controls (D60): what Jimmy uses, and the limits they set.

- `usage()` measures every part, for Settings → Storage & performance.
- `enforce(store)` keeps captures to RETENTION_DAYS and the captures + thumbnails under
  STORAGE_CAP_GB, deleting the oldest whole days first (through Store.forget, so text,
  speech, vectors and thumbnails go together) and never today. Both 0 = keep everything.
- `clear(what)` empties a cache on request: downloads, old logs, the meaning-search index.

Run at startup and with the idle compaction (bus._maybe_compact). Nothing here deletes
without the user having set a limit or pressed a button.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import config

DAY_MS = 86_400_000


def _size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    stack = [p]
    while stack:
        d = stack.pop()
        try:
            with __import__("os").scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return total


def _files(base: Path, *names: str) -> int:
    return sum(_size(base.with_name(base.name + n)) if n else _size(base) for n in names)


def usage() -> dict:
    """Bytes per part. `app` and `runtime` only for an installed copy."""
    from jimmy import config as jcfg
    from jimmy import install
    data = config.DATA_DIR
    out = {"captures": _files(config.DB_PATH, "", "-wal", "-shm"),
           "thumbnails": _size(config.THUMB_DIR) if hasattr(config, "THUMB_DIR") else _size(data / "thumbs"),
           "memory": _files(jcfg.MEMORY_DB, "", "-wal", "-shm"),
           "models": _size(data / "models"), "cache": _size(data / "cache"), "logs": _size(data / "logs")}
    if install.INSTALLED:
        out["runtime"] = _size(data / "runtime") + _size(data / "ollama")   # D61: Jimmy's Python, local AI
    out["total"] = sum(out.values())
    return {"bytes": out, "data_dir": str(data), "retention_days": config.RETENTION_DAYS,
            "storage_cap_gb": config.STORAGE_CAP_GB}


def _day_start(ms: int) -> int:
    lt = time.localtime(ms / 1000)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def enforce(store, now_ms: int | None = None, days: int | None = None, cap_gb: float | None = None) -> dict:
    """Apply the user's limits. Returns what went: {"days": [...], "frames": n}."""
    now = now_ms or int(time.time() * 1000)
    days = config.RETENTION_DAYS if days is None else days
    cap = config.STORAGE_CAP_GB if cap_gb is None else cap_gb
    today = _day_start(now)
    gone, frames = [], 0
    if days > 0:
        cut = today - (days - 1) * DAY_MS                   # keep today and the days-1 before it
        first = _oldest(store)
        if first is not None and first < cut:
            frames += store.forget(0, cut).get("frames", 0)
            gone.append(f"before {time.strftime('%Y-%m-%d', time.localtime(cut / 1000))}")
    if cap > 0:
        limit = cap * 1e9
        for _ in range(3660):                               # at most ten years, one day at a time
            used = _files(Path(store.path), "", "-wal") + _size(config.DATA_DIR / "thumbs")
            first = _oldest(store)
            if used <= limit or first is None or _day_start(first) >= today:
                break                                       # under the cap, or only today left
            d0 = _day_start(first)
            frames += store.forget(d0, d0 + DAY_MS).get("frames", 0)
            gone.append(time.strftime("%Y-%m-%d", time.localtime(d0 / 1000)))
    if gone:
        print(f"[storage] limits ({days} days, {cap:g} GB): removed {', '.join(gone)} ({frames} screenshots)")
    return {"days": gone, "frames": frames}


def _oldest(store) -> int | None:
    with store._lock:
        a = store.conn.execute("SELECT MIN(ts) FROM frames").fetchone()[0]
        b = store.conn.execute("SELECT MIN(ts_start) FROM audio_segments").fetchone()[0]
    xs = [x for x in (a, b) if x is not None]
    return min(xs) if xs else None


def clear(what: str, store=None) -> int:
    """Empty one cache; returns bytes freed. "cache": downloads (uv, pip, partial models);
    "logs": rotated logs (the live one stays); "index": meaning-search vectors (rebuilt
    while Jimmy runs, if local AI is on)."""
    data = config.DATA_DIR
    if what == "cache":
        before = _size(data / "cache")
        shutil.rmtree(data / "cache", ignore_errors=True)
        return before
    if what == "logs":
        freed = 0
        for p in (data / "logs").glob("*.log.*"):
            freed += _size(p)
            p.unlink(missing_ok=True)
        return freed
    if what == "index" and store is not None:
        before = store.size()
        with store._lock:
            store.conn.execute("DELETE FROM embeddings")
            store.conn.commit()
        store.compact()
        return max(0, before - store.size())
    raise ValueError(f"nothing called {what!r} to clear")


if __name__ == "__main__":
    import tempfile
    from .db import Store
    d = Path(tempfile.mkdtemp())
    config.DATA_DIR = d
    s = Store(str(d / "ambient.db"))
    now = int(time.time() * 1000)
    w = s.open_window(kind="app", ts=now - 40 * DAY_MS)
    for age in (40, 10, 1, 0):
        s.add_frame(w, "app", "title", None, 0, now - age * DAY_MS, None)
    out = enforce(s, now, days=7, cap_gb=0)
    with s._lock:
        left = s.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    assert left == 2 and out["frames"] == 2, (left, out)
    out = enforce(s, now, days=0, cap_gb=1e-12)            # a tiny cap: everything but today goes
    with s._lock:
        ages = [round((now - r[0]) / DAY_MS) for r in s.conn.execute("SELECT ts FROM frames")]
    assert ages == [0], ages
    print("storage.py self-check ok;", usage()["bytes"]["captures"], "bytes of captures in the test db")
