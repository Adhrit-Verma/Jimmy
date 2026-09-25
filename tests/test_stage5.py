"""One runnable check for stage 5 (recall timeline). `python tests/test_stage5.py`.

The embedding model is replaced by a tiny deterministic one (hashed words), so
this runs without Ollama; it tests the plumbing, not bge-m3's quality.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ambient.recall as recall  # noqa: E402
from ambient.api import OverlayAPI  # noqa: E402
from ambient.db import Store  # noqa: E402

MIN = 60_000
T0 = 1_800_000_000_000
SYN = {"consulting": "mckinsey", "firm": "mckinsey"}   # a pretend "meaning": synonyms share a slot


VOCAB: dict[str, int] = {}


def fake_embed(texts, model=None):
    """Bag of words with one slot per distinct word: no hash collisions, so the
    only "meaning" is the SYN table (a hashed version collided and failed)."""
    out = []
    for t in texts:
        v = np.zeros(512, dtype=np.float32)
        for w in t.lower().split():
            w = SYN.get(w.strip(".,?"), w.strip(".,?"))
            v[VOCAB.setdefault(w, len(VOCAB)) % 512] += 1.0
        out.append(v.tolist())
    return out


recall.embed = fake_embed


def store_with_history() -> Store:
    s = Store(":memory:")
    for i in range(4):   # a sidebar line in 4 windows = furniture
        w = s.open_window(ts=T0 + i)
        f = s.add_frame(w, "claude.exe", "Claude", ts=T0 + i * MIN, thumb_path=f"thumbs/x/{i}.jpg")
        s.add_text(f, "uia", f"Image suspicion check sidebar\nlunch notes number {i}")
    w = s.open_window(ts=T0 + 10 * MIN)
    f = s.add_frame(w, "chrome.exe", "McKinsey Forward Application", ts=T0 + 10 * MIN)
    s.add_text(f, "uia", "McKinsey Forward application form\nApplications close on Monday")
    s.add_audio(T0 + 12 * MIN, T0 + 12 * MIN + 5000, "mic", "the agent development kit from google")
    return s


def test_chunks_split_on_lines():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(30))
    parts = recall.chunks(text, size=800)
    assert all(len(p) <= 800 for p in parts) and len(parts) > 1
    assert "".join(parts).replace("\n", "") == text.replace("\n", ""), "nothing lost, nothing added"
    assert recall.chunks("  \n\n") == []
    print("ok  chunking")


def test_index_is_incremental_and_semantic_finds_meaning():
    s = store_with_history()
    first = recall.index(s, model="fake")
    assert first > 0 and recall.index(s, model="fake") == 0, "already indexed blocks aren't redone"
    s.add_audio(T0 + 20 * MIN, T0 + 20 * MIN + 1, "mic", "new speech later")
    assert recall.index(s, model="fake") == 1, "only the new block"
    hits = recall.semantic(s, "consulting firm", model="fake")
    assert hits and "McKinsey" in hits[0]["chunk"], "a synonym finds it by meaning"
    assert recall.semantic(Store(":memory:"), "anything", model="fake") == [], "empty index, no results"
    print("ok  incremental index, meaning search")


def test_hybrid_merges_strips_furniture_and_dedupes():
    s = store_with_history()
    recall.index(s)
    recall._furniture["at"] = 0                     # fresh furniture for this store
    hits = recall.hybrid(s, "mckinsey application", k=10)
    assert hits[0]["app"] == "chrome.exe" and "words" in hits[0]["via"] and "meaning" in hits[0]["via"]
    texts = [h["text"] for h in recall.hybrid(s, "image suspicion check lunch", k=10)]
    assert all("Image suspicion check sidebar" not in t for t in texts), "sidebar furniture is stripped"
    assert len(texts) == len(set(texts)), "no duplicate texts"
    print("ok  hybrid: merged, furniture stripped, deduped")


def test_hybrid_survives_without_embedding_model():
    def down(texts, model=None):
        raise recall.LLMError("unreachable")
    s = store_with_history()
    saved, recall.embed = recall.embed, down
    try:
        hits = recall.hybrid(s, "McKinsey application")
        assert hits and all(h["via"] == "words" for h in hits), "keywords still answer"
    finally:
        recall.embed = saved
    print("ok  keyword fallback when the model is down")


def test_timeline_api_and_thumb_traversal():
    import tempfile
    from ambient import config
    s = store_with_history()
    with tempfile.TemporaryDirectory() as d:
        saved = (config.DATA_DIR, config.THUMB_DIR)
        config.DATA_DIR, config.THUMB_DIR = Path(d), Path(d) / "thumbs"
        (Path(d) / "thumbs" / "x").mkdir(parents=True)
        (Path(d) / "thumbs" / "x" / "0.jpg").write_bytes(b"\xff\xd8jpeg")
        (Path(d) / "secret.txt").write_text("private")
        api = OverlayAPI({"state": lambda: {}, "pause": print, "resume": print, "dismiss": print,
                          **recall.timeline_hooks(s)}).start()
        get = lambda route: json.load(urllib.request.urlopen(urllib.request.Request(  # noqa: E731
            f"{api.url}/{route}", headers={"Authorization": f"Bearer {api.token}"}), timeout=5))
        try:
            day = __import__("time").strftime("%Y-%m-%d", __import__("time").localtime(T0 / 1000))
            tl = get(f"timeline?day={day}")
            assert tl["day"] == day and len(tl["frames"]) == 5 and day in tl["days"]
            fr = get(f"frame?id={tl['frames'][-1]['id']}")
            assert "McKinsey" in fr["text"][0]["text"] and fr["speech"], "frame text + nearby speech"
            assert get("thumb?path=thumbs/x/0.jpg")["data"].startswith("data:image/jpeg;base64,")
            for evil in ("thumb?path=secret.txt", "thumb?path=thumbs/../secret.txt"):
                try:
                    get(evil)
                except urllib.error.HTTPError as e:
                    assert e.code == 404
                else:
                    raise AssertionError(f"{evil} must not be served")
            assert get("search?q=mckinsey")["results"], "search route answers"
        finally:
            api.stop()
            config.DATA_DIR, config.THUMB_DIR = saved
    print("ok  timeline API; thumbs can't escape their folder")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
