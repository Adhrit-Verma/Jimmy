"""Stage 5: the recall timeline's search (D24).

Two searches, merged: FTS5 keywords (exact words, already there since Stage 1)
and meaning (bge-m3 vectors, local via Ollama), so "pricing page" also finds
"plans & billing". Both are bounded by the same time phrases Jimmy understands.

The embedding call lives in the Jimmy core's one client (invariant 7), reached
through `jimmy.core.embed`; this module only stores and compares vectors.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import chain
from pathlib import Path

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
    pages = store.vector_pages(model, since_ms, until_ms)
    first = next(pages, None)
    if first is None:
        return []
    q = np.asarray(embed([query], model)[0], dtype=np.float32)
    q /= np.linalg.norm(q) + 1e-9
    # D38: one page of vectors at a time; only the ids and scores are kept (12 bytes
    # a chunk), and text is fetched for the winners alone. Same order, same ranking.
    ids, scores = [], []
    for page in chain([first], pages):            # chain, not (first, *pages): that loads them all
        mat = np.frombuffer(b"".join(v for _, v in page), dtype=np.float32).reshape(len(page), -1)
        scores.append(mat @ q)
        ids.append(np.fromiter((i for i, _ in page), dtype=np.int64, count=len(page)))
        del mat, page                             # one page alive at a time
    scores, ids = np.concatenate(scores), np.concatenate(ids)
    best = np.argsort(-scores)[:k]
    rows = store.vector_rows([int(ids[i]) for i in best])
    return [{**rows[int(ids[i])], "score": float(scores[i])} for i in best]


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
    from .redact import is_own_window
    junk = furniture(store)
    out, seen_text = [], set()
    for r in sorted(merged.values(), key=lambda r: -r["score"]):
        if is_own_window(r.get("app"), r.get("title")):
            continue                  # Jimmy's own windows, captured before D25 excluded them
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

    D38: kept up to date incrementally. A refresh (at most every 10 minutes) reads
    only the blocks stored since the last one, and a line that has reached the
    threshold stops carrying its set of windows. Same lines as a full rebuild.
    ponytail: the per-line map lives in RAM, ~100 B a distinct line; move it to a
    SQL table (gate.line_windows too) if months of history make it heavy.
    """
    import time

    from . import config
    now = time.time()
    need = min_windows or config.PERSISTENT_LINE_WINDOWS
    st = _furniture
    if now - st["at"] < ttl_s and st.get("store") is store and st.get("need") == need:
        return st["lines"]
    if st.get("store") is not store or st.get("need") != need:
        st.update(store=store, need=need, last=0, seen={}, furniture=set())
    seen, found = st["seen"], st["furniture"]
    last = st["last"]
    for bid, wid, text in store.blocks_after(st["last"]):
        last = bid
        for ln in text.split("\n"):
            ln = ln.strip()
            if not ln or ln in found:
                continue
            windows = seen.setdefault(ln, set())
            windows.add(wid)
            if len(windows) >= need:
                found.add(ln)
                del seen[ln]               # furniture now; its windows no longer matter
    st.update(at=now, last=last, lines=frozenset(found))
    return st["lines"]


# --- the timeline window's reads (served by ambient/api.py) -----------------

def timeline_hooks(store: Store) -> dict:
    """GET handlers for the timeline window, as OverlayAPI hooks (get_<route>)."""
    import base64
    import time
    from datetime import datetime

    from . import config

    days_cache: dict = {"key": None, "days": []}

    def get_timeline(p: dict) -> dict:
        # D38: the day list scans every frame; reuse it until a frame is added.
        key = store.last_frame_id()
        if key != days_cache["key"]:
            days_cache.update(key=key, days=store.days())
        days = days_cache["days"]
        day = p.get("day") or (days[0] if days else time.strftime("%Y-%m-%d"))
        start = int(datetime.strptime(day, "%Y-%m-%d").timestamp() * 1000)
        from .redact import is_own_window
        from .insights import app_name
        frames = [{**f, "name": app_name(f["app"])} for f in store.timeline(start, start + 86_400_000 - 1)
                  if not is_own_window(f["app"], f["title"])]
        return {"day": day, "days": days, "frames": frames}

    def get_frame(p: dict) -> dict | None:
        return store.frame(int(p["id"]))

    def get_thumb(p: dict) -> dict | None:
        # Only files inside the thumbnail folder, whatever the path says.
        path = (config.DATA_DIR / p["path"]).resolve()
        if config.THUMB_DIR.resolve() not in path.parents or not path.is_file():
            return None
        data = _small(str(path), int(p["w"])) if p.get("w") else path.read_bytes()
        return {"data": "data:image/jpeg;base64," + base64.b64encode(data).decode()}

    def get_insights(p: dict) -> dict:
        from .insights import day
        return day(store, p.get("day") or None)

    def get_search(p: dict) -> dict:
        from .plugin import time_window
        q = p["q"].strip()
        w = time_window(q, int(time.time() * 1000))
        hits = hybrid(store, q, w[0] if w else 0, w[1] if w else 1 << 62, 20) if q else []
        return {"window": w[2] if w else None, "results": hits}

    return {"get_timeline": get_timeline, "get_frame": get_frame, "get_thumb": get_thumb,
            "get_search": get_search, "get_insights": get_insights}


@lru_cache(maxsize=600)
def _small(path: str, width: int) -> bytes:
    """A thumbnail scaled down for the scrub strip: a day of 1280-wide JPEGs as
    base64 over IPC was ~150 KB a tile (D31). Undecodable files come back as-is.
    ponytail: keyed by path, so a file rewritten in place would serve stale; thumbs never are."""
    import cv2
    raw = Path(path).read_bytes()
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    width = max(64, min(1280, width))
    if img is None or img.shape[1] <= width:
        return raw
    small = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 72])
    return buf.tobytes() if ok else raw
