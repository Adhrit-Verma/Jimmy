"""CLI: python -m ambient {run,search,stats,doctor}"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config


def _doctor() -> int:
    """Report what actually works on this machine. Cheap to run, saves guessing."""
    rows: list[tuple[str, bool, str]] = []

    def check(name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        rows.append((name, ok, detail))

    def _screen():
        from . import screen
        src = screen.ScreenSource()
        for _ in range(5):
            f = src.grab(300)
            if f is not None:
                return True, f"{f.shape[1]}x{f.shape[0]} bgr"
            time.sleep(0.2)
        return False, "no frame in 5 tries (locked screen or secure desktop?)"

    def _uia():
        from . import screen
        aw = screen.active_window()
        wt = screen.window_text(aw.hwnd) if aw.hwnd else None
        if not wt:
            return False, "no foreground window"
        return True, (f"{aw.app} | {len(wt.text)} chars from {wt.nodes} nodes "
                      f"in {wt.elapsed*1000:.0f}ms{' (truncated)' if wt.truncated else ''}")

    def _faces():
        from .redact import FaceStage
        fs = FaceStage()
        return fs.available, ("models present" if fs.available
                              else f"missing onnx in {config.MODELS_DIR}")

    def _ocr():
        from . import screen
        return screen.ocr_available(), ("tesseract present" if screen.ocr_available()
                                        else "no tesseract binary; UIA-only (canvas/video lost)")

    def _whisper():
        import ctranslate2
        n = ctranslate2.get_cuda_device_count()
        return n > 0, f"cuda devices={n} compute={sorted(ctranslate2.get_supported_compute_types('cuda')) if n else 'cpu'}"

    def _audio():
        import numpy as np
        import pyaudiowpatch as pa
        from .audio import input_devices, pick_mic, to_mono16k
        with pa.PyAudio() as p:
            mic = pick_mic(p)
            others = [d["name"] for d in input_devices(p) if d["index"] != mic["index"]]
            rate, ch = int(mic["defaultSampleRate"]), min(2, int(mic["maxInputChannels"]))
            print(f"  ....  mic test        speak now for 3 s into {mic['name']!r} ...", flush=True)
            s = p.open(format=pa.paInt16, channels=ch, rate=rate, input=True,
                       frames_per_buffer=1024, input_device_index=mic["index"])
            raw = b"".join(s.read(1024, exception_on_overflow=False)
                           for _ in range(int(rate * 3 / 1024)))
            s.stop_stream(); s.close()
        peak = float(np.abs(to_mono16k(raw, rate, ch)).max())
        # Near-silence is not proof of a broken mic: noise suppression gates a quiet
        # room to (almost) zero. Only hearing speech-level sound proves it works.
        heard = peak >= config.MIN_SEGMENT_RMS
        detail = (f"{mic['name']}: peak {peak:.0f}, "
                  + ("hears speech-level sound" if heard else
                     "near-silent. If you spoke, set MIC_DEVICE in ambient/config.py")
                  + (f" | other inputs: {', '.join(others)}" if others and not heard else ""))
        return heard, detail

    def _db():
        from .db import Store
        s = Store(config.DB_PATH)
        st = s.stats()
        s.close()
        return True, f"{config.DB_PATH} frames={st['frames']} text={st['text_blocks']}"

    for name, fn in (("screen (dxgi)", _screen), ("uia text", _uia), ("face models", _faces),
                     ("ocr", _ocr), ("whisper/cuda", _whisper), ("audio (wasapi)", _audio),
                     ("store", _db)):
        check(name, fn)

    width = max(len(r[0]) for r in rows)
    bad = 0
    for name, ok, detail in rows:
        mark = "ok  " if ok else "FAIL"
        bad += 0 if ok else 1
        print(f"  {mark}  {name.ljust(width)}  {detail}")
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ambient", description="Jimmy ambient layer, stage 1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="capture until ctrl-c")
    r.add_argument("--seconds", type=float, default=None)
    r.add_argument("--monitor", type=int, default=None)
    r.add_argument("--no-audio", action="store_true")
    r.add_argument("--no-thumbs", action="store_true")
    r.add_argument("--db", default=None)

    s = sub.add_parser("search", help="full-text search screen and speech")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--db", default=None)

    st = sub.add_parser("stats", help="row counts and coverage")
    st.add_argument("--db", default=None)
    st.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="check every component on this machine")

    a = ap.parse_args(argv)

    if a.cmd == "doctor":
        return _doctor()

    from .db import Store
    db = a.db or config.DB_PATH

    if a.cmd == "run":
        from .bus import ContextBus
        bus = ContextBus(db_path=db, monitor=a.monitor,
                         audio=not a.no_audio, thumbs=not a.no_thumbs)
        counters = bus.run(duration_s=a.seconds)
        print(json.dumps(counters.as_dict(), indent=2))
        return 0

    if a.cmd == "search":
        with Store(db) as store:
            hits = store.search(a.query, a.limit)
        if not hits:
            print("no matches")
            return 1
        for h in hits:
            when = time.strftime("%a %d %b %H:%M", time.localtime(h["ts"] / 1000))
            where = h["title"] or h["app"] or h["source"]
            print(f"{when}  [{h['kind']}/{h['source']}]  {(where or '')[:48]}")
            print(f"    {h['snippet']}")
        return 0

    if a.cmd == "stats":
        with Store(db) as store:
            out = store.stats()
        if a.json:
            print(json.dumps(out, indent=2))
        else:
            for k, v in out.items():
                if k.endswith("_ms") and v:
                    v = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v / 1000))
                print(f"  {k:18s} {v}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
