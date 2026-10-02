"""Equivalence check for changes to db.py / recall.py / insights.py / gate.py (D38).

Runs 43 read paths (search + snippets, meaning search, hybrid, nearest frame,
furniture, word rarity, insights, the gate's line map) on a frozen copy of the
real DB and saves their outputs, so an optimisation can be proven to change
nothing. Needs data/ambient.db and Ollama (bge-m3). Not part of the offline suites.

    python tests/equiv_db.py snap before     # on the old code
    python tests/equiv_db.py snap after      # on the new code
    python tests/equiv_db.py diff            # identical? (meaning scores may differ below 1e-5)
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = Path(tempfile.gettempdir()) / "jimmy-equiv"
FROZEN = WORK / "frozen.db"
NOW = 1790940000000          # a fixed "now", so time windows don't drift between runs

QUERIES = ["mckinsey application form", "resume skills", "discord voice channel", "gcp learning",
           "jimmy timeline", "pricing", "what did I read about python", "instagram", "spotify playlist",
           "word count", "deadline monday", "hello"]


def snap(tag: str) -> None:
    from ambient import insights, recall
    from ambient.db import Store
    from ambient.gate import Gate
    from jimmy.memory import fts_query
    WORK.mkdir(exist_ok=True)
    if not FROZEN.exists():
        shutil.copy(ROOT / "data" / "ambient.db", FROZEN)
    work = WORK / f"work-{tag}.db"
    shutil.copy(FROZEN, work)
    s = Store(work)
    out = {}
    recall._furniture["at"] = 0
    out["furniture"] = sorted(recall.furniture(s))
    for q in QUERIES:
        fq = fts_query(q)
        out[f"search:{q}"] = s.search(fq, 24, 0, 1 << 62, 48) if fq else []
        out[f"hybrid:{q}"] = [{k: h[k] for k in ("ref", "ts", "app", "title", "text", "via")}
                              for h in recall.hybrid(s, q, 0, 1 << 62, 12)]
        out[f"semantic:{q}"] = recall.semantic(s, q, 0, 1 << 62, 20)
    refs = [r[0] for r in s.conn.execute("select id from text_blocks order by id limit 40")]
    refs += [-r[0] for r in s.conn.execute("select id from audio_segments order by id limit 40")]
    ts = {r: (s.conn.execute("select f.ts from text_blocks t join frames f on f.id=t.frame_id where t.id=?", (r,))
              if r > 0 else s.conn.execute("select ts_start from audio_segments where id=?", (-r,))).fetchone()[0]
          for r in refs}
    out["frame_for"] = [s.frame_for(r, ts[r]) for r in refs]
    out["unembedded"] = s.unembedded("bge-m3", 1000)
    out["term_share"] = [s.term_share(w, NOW) for w in ("discord", "claude", "resume", "mckinsey", "zzz")]
    out["insights"] = insights.day(s, "2026-10-02", NOW)
    g = Gate(s, None, history_until=NOW)
    out["gate_lines"] = len(g.line_windows)
    out["distinctive"] = g._distinctive("McKinsey Forward application form closes Monday resume skills discord", NOW)
    s.close()
    (WORK / f"equiv-{tag}.json").write_text(json.dumps(out, default=str, sort_keys=True), encoding="utf-8")
    print(f"snapshot {tag}: {len(out)} read paths -> {WORK}")


def diff() -> int:
    a = json.loads((WORK / "equiv-before.json").read_text(encoding="utf-8"))
    b = json.loads((WORK / "equiv-after.json").read_text(encoding="utf-8"))
    bad = []
    for k in a:
        x, y = a[k], b.get(k)
        if k.startswith("semantic:") and isinstance(y, list) and len(x) == len(y):
            same = all({kk: v for kk, v in p.items() if kk != "score"} == {kk: v for kk, v in q.items() if kk != "score"}
                       and abs(p["score"] - q["score"]) < 1e-5 for p, q in zip(x, y))
        else:
            same = x == y
        if not same:
            bad.append(k)
            print("DIFF", k)
    print("identical" if not bad else f"{len(bad)} read paths differ", f"({len(a)} compared)")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["snap"]:
        snap(sys.argv[2])
    else:
        sys.exit(diff())
