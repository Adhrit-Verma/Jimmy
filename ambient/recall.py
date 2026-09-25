"""Stage 5: the recall timeline's search (D24).

Two searches, merged: FTS5 keywords (exact words, already there since Stage 1)
and meaning (bge-m3 vectors, local via Ollama), so "pricing page" also finds
"plans & billing". Both are bounded by the same time phrases Jimmy understands.

The embedding call lives in the Jimmy core's one client (invariant 7), reached
through `jimmy.core.embed`; this module only stores and compares vectors.
"""
from __future__ import annotations

import numpy as np

from jimmy import config as jcfg
from jimmy.core import LLMError, embed
from jimmy.memory import fts_query

from .db import Store

CHUNK_CHARS = 800          # bge-m3 takes far more; smaller chunks match more precisely
RRF_K = 60                 # reciprocal-rank fusion constant (the usual value)


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on line boundaries into pieces of at most ~`size` characters."""
    out, cur = [], ""
    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue
        if cur and len(cur) + len(line) + 1 > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line[:size]
    if cur:
        out.append(cur)
    return out


def index(store: Store, batch: int = 32, limit: int = 400, model: str | None = None) -> int:
    """Embed up to `limit` unindexed blocks. Returns chunks embedded (0 = caught up).

    Raises LLMError if the embedding model is unreachable; callers decide
    whether that matters (the live indexer just tries again later).
    """
    model = model or jcfg.EMBED_MODEL
    todo = [(r["ref"], r["ts"], c) for r in store.unembedded(model, limit) for c in chunks(r["text"])]
    done = 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        vecs = np.asarray(embed([c for _, _, c in part], model), dtype=np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9   # cosine = dot product
        store.add_embeddings([(ref, ts, model, c, v.tobytes()) for (ref, ts, c), v in zip(part, vecs)])
        done += len(part)
    return done


def semantic(store: Store, query: str, since_ms: int = 0, until_ms: int = 1 << 62,
             k: int = 20, model: str | None = None) -> list[dict]:
    """Nearest chunks by meaning, best first. Empty if nothing is indexed yet.

    ponytail: brute force over every vector in the window (numpy, ~1k dims).
    Fine for weeks of captures; switch to sqlite-vec or an ANN index if a
    month-wide query gets slow.
    """
    model = model or jcfg.EMBED_MODEL
    rows = store.vectors(model, since_ms, until_ms)
    if not rows:
        return []
    q = np.asarray(embed([query], model)[0], dtype=np.float32)
    q /= np.linalg.norm(q) + 1e-9
    mat = np.frombuffer(b"".join(r["vec"] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    scores = mat @ q
    best = np.argsort(-scores)[:k]
    return [{**{k2: v for k2, v in rows[i].items() if k2 != "vec"}, "score": float(scores[i])}
            for i in best]


def hybrid(store: Store, query: str, since_ms: int = 0, until_ms: int = 1 << 62,
           k: int = 12) -> list[dict]:
    """Keyword and meaning results merged by reciprocal-rank fusion, one row per
    captured block: {ref, ts, app, title, frame_id, source, text, via}."""
    merged: dict[int, dict] = {}

    def add(rank: int, ref: int, row: dict, via: str) -> None:
        cur = merged.setdefault(ref, {**row, "ref": ref, "score": 0.0, "via": set()})
        cur["score"] += 1.0 / (RRF_K + rank)
        cur["via"].add(via)

    q = fts_query(query)
    if q:
        for rank, h in enumerate(store.search(q, k * 2, since_ms, until_ms, 48)):
            add(rank, h["ref"], {"ts": h["ts"], "app": h["app"], "title": h["title"],
                                 "source": h["source"], "frame_id": None,
                                 "text": h["snippet"].replace("[", "").replace("]", "")}, "words")
    try:
        sem = semantic(store, query, since_ms, until_ms, k * 2)
    except LLMError:
        sem = []                   # no embedding model: keywords alone still answer
    seen_ref: set[int] = set()
    for rank, h in enumerate(sem):
        if h["ref"] in seen_ref:   # several chunks of one block: count its best only
            continue
        seen_ref.add(h["ref"])
        add(rank, h["ref"], {"ts": h["ts"], "app": h["app"], "title": h["title"],
                             "source": h["source"], "frame_id": h["frame_id"],
                             "text": h["chunk"]}, "meaning")
    # Strip screen furniture (browser chrome, sidebar chat lists: lines seen in
    # >= 3 windows, as the gate does, D22) and collapse repeats of the same text.
    # The first timeline search listed Claude's sidebar three times.
    junk = furniture(store)
    out, seen_text = [], set()
    for r in sorted(merged.values(), key=lambda r: -r["score"]):
        text = "\n".join(ln for ln in (x.strip() for x in r["text"].split("\n")) if ln and ln not in junk)
        key = " ".join(text.lower().split())[:200]
        if not text or key in seen_text:
            continue
        seen_text.add(key)
        out.append({**r, "text": text, "via": "+".join(sorted(r["via"]))})
        if len(out) >= k:
            break
    return out


_furniture: dict = {"at": 0.0, "lines": frozenset()}


def furniture(store: Store, min_windows: int | None = None, ttl_s: float = 600) -> frozenset:
    """Lines that appear in several capture windows: interface, not content.

    ponytail: recomputed from every stored block at most every 10 minutes. Fine
    for weeks of captures; keep a running table if it gets slow.
    """
    import time
    from collections import defaultdict

    from . import config
    now = time.time()
    if now - _furniture["at"] < ttl_s and _furniture.get("store") is store:
        return _furniture["lines"]
    need = min_windows or config.PERSISTENT_LINE_WINDOWS
    seen: dict[str, set] = defaultdict(set)
    for wid, text in store.blocks_before(1 << 62):
        for ln in text.split("\n"):
            ln = ln.strip()
            if ln:
                seen[ln].add(wid)
    lines = frozenset(ln for ln, w in seen.items() if len(w) >= need)
    _furniture.update(at=now, lines=lines, store=store)
    return lines


# --- the timeline window's reads (served by ambient/api.py) -----------------

def timeline_hooks(store: Store) -> dict:
    """GET handlers for the timeline window, as OverlayAPI hooks (get_<route>)."""
    import base64
    import time
    from datetime import datetime

    from . import config

    def get_timeline(p: dict) -> dict:
        days = store.days()
        day = p.get("day") or (days[0] if days else time.strftime("%Y-%m-%d"))
        start = int(datetime.strptime(day, "%Y-%m-%d").timestamp() * 1000)
        return {"day": day, "days": days, "frames": store.timeline(start, start + 86_400_000 - 1)}

    def get_frame(p: dict) -> dict | None:
        return store.frame(int(p["id"]))

    def get_thumb(p: dict) -> dict | None:
        # Only files inside the thumbnail folder, whatever the path says.
        path = (config.DATA_DIR / p["path"]).resolve()
        if config.THUMB_DIR.resolve() not in path.parents or not path.is_file():
            return None
        return {"data": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()}

    def get_search(p: dict) -> dict:
        from .plugin import time_window
        q = p["q"].strip()
        w = time_window(q, int(time.time() * 1000))
        hits = hybrid(store, q, w[0] if w else 0, w[1] if w else 1 << 62, 20) if q else []
        return {"window": w[2] if w else None, "results": hits}

    return {"get_timeline": get_timeline, "get_frame": get_frame,
            "get_thumb": get_thumb, "get_search": get_search}
