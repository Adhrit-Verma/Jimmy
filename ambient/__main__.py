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

    def _uia_cache():
        """D47: the cached control lookup must find what the old walk finds, faster."""
        from . import act, screen
        aw = screen.active_window()
        if not aw.hwnd:
            return False, "no foreground window"
        t0 = time.perf_counter()
        walk = act._controls_walk(aw.hwnd)
        t1 = time.perf_counter()
        cached = act._controls_cached(aw.hwnd)
        t2 = time.perf_counter()
        same = [(x.name, x.kind) for x in walk] == [(x.name, x.kind) for x in cached]
        return same, (f"{len(cached)} controls in {(t2 - t1) * 1000:.0f} ms cached vs {len(walk)} in "
                      f"{(t1 - t0) * 1000:.0f} ms walked" + ("" if same else ": DIFFERENT, set UIA_CACHE = False"))

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

    def _vad():
        """D50: the configured voice detector, and the wake word if it's on."""
        from .audio import WakeWord, make_vad
        v = make_vad()
        want = config.VAD_ENGINE.lower()
        got = "silero" if type(v).__name__ == "SileroVad" else "webrtc"
        ok, detail = got == want, f"{got} ({v.frame_ms} ms frames)" + ("" if got == want else f", wanted {want}")
        if config.PAUSE_WAKEWORD:
            w = WakeWord.load()
            ok = ok and w is not None
            detail += "; wake word " + ("loaded" if w else f"missing ({config.WAKEWORD_MODEL})")
        return ok, detail

    def _db():
        from .db import Store
        s = Store(config.DB_PATH)
        st = s.stats()
        s.close()
        return True, f"{config.DB_PATH} frames={st['frames']} text={st['text_blocks']}"

    for name, fn in (("screen (dxgi)", _screen), ("uia text", _uia), ("uia controls (cached)", _uia_cache),
                     ("face models", _faces),
                     ("ocr", _ocr), ("whisper/cuda", _whisper), ("audio (wasapi)", _audio),
                     ("voice detector", _vad),
                     ("store", _db)):
        check(name, fn)

    width = max(len(r[0]) for r in rows)
    bad = 0
    for name, ok, detail in rows:
        mark = "ok  " if ok else "FAIL"
        bad += 0 if ok else 1
        print(f"  {mark}  {name.ljust(width)}  {detail}")
    return 0 if bad == 0 else 1


def _replay(a) -> int:
    """Stage 3's GO/NO-GO: <= 10 cards in any replayed hour, each defensible."""
    from datetime import datetime

    from jimmy import config as jcfg
    from jimmy.cards import default_engine
    from jimmy.memory import Memory

    from .db import Store
    from .gate import replay

    ms = lambda s, d: int(datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp() * 1000) if s else d  # noqa: E731
    hm = lambda t: time.strftime("%a %d %H:%M", time.localtime(t / 1000)) if t else "--"  # noqa: E731
    engine = None if a.dry else default_engine()
    if engine and not engine.llm.configured:
        print("no API key: running dry (Tier 1 only)")
        engine = None
    memory = Memory(jcfg.MEMORY_DB)
    with Store(a.db or config.DB_PATH) as store:
        r = replay(store, ms(a.since, 0), ms(a.until, int(time.time() * 1000)), engine, memory, a.intent)
    memory.close()

    for cand, card, why in r["decisions"]:
        verdict = f"CARD  {card.line!r}" if card else why
        print(f"{hm(cand.ts)}  {cand.type:6s} [{cand.reason}]\n        -> {verdict}")
    print(f"\nreplayed {r['events']} events over {r['hours']:.2f} h of captured time")
    for k, v in sorted(r["stats"].items()):
        print(f"  {k:36s} {v}")
    n, per_h = len(r["cards"]), len(r["cards"]) / r["hours"] if r["hours"] else 0.0
    ok = r["worst_hour"] <= 10
    print(f"\ncards: {n} ({per_h:.1f}/h); worst rolling hour: {r['worst_hour']}"
          f"  ->  {'GO on count' if ok else 'NO-GO: tune the gate and replay'}"
          + ("" if engine else "  (dry run: count not meaningful)"))
    if ok and n:
        print("The count passes. Each card still has to be one you'd defend: read them above.")
    return 0 if ok else 1


def _deadlines(a) -> int:
    """List what the deadline catcher stored, or run it over history (D32)."""
    from . import proactive
    from .db import Store
    from .recall import furniture
    fmt = lambda ts: time.strftime("%a %d %b %H:%M", time.localtime(ts / 1000))  # noqa: E731
    with Store(a.db or config.DB_PATH) as store:
        if a.scan:
            rows, _, _ = store.new_text(0, 0, limit=1 << 30)
            if a.dry:
                junk = furniture(store)
                for r in rows:
                    for line in (ln.strip() for ln in r["text"].split("\n")):
                        got = (12 <= len(line) <= 240 and line not in junk and proactive._DUE_WORDS.search(line)
                               and proactive.parse_due(line, r["ts"]))
                        if got:
                            print(f"seen {fmt(r['ts'])}  due {fmt(got[0])}  {line[:110]}")
                return 0
            from jimmy.cards import local_engine
            engine = local_engine()
            n = proactive.find_deadlines(rows, engine.is_deadline, furniture(store), store, [1 << 30])
            print(f"{n} new deadline(s) ({engine.calls} model checks)")
        for d in store.deadlines():
            print(f"due {fmt(d['due_ts'])}  [{d['state']}]  {d['text'][:110]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # captured text on a cp1252 console
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="ambient", description="Jimmy ambient layer, stage 1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="capture until ctrl-c")
    r.add_argument("--seconds", type=float, default=None)
    r.add_argument("--monitor", type=int, default=None)
    r.add_argument("--no-audio", action="store_true")
    r.add_argument("--no-thumbs", action="store_true")
    r.add_argument("--no-cards", action="store_true", help="capture only, no trigger gate")
    r.add_argument("--no-overlay", action="store_true", help="console only, no on-screen overlay")
    r.add_argument("--demo", nargs="?", const="default", default=None,
                   help="play a scripted walkthrough for a screen recording (optionally your own script file)")
    r.add_argument("--db", default=None)

    s = sub.add_parser("search", help="full-text search screen and speech")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--db", default=None)

    st = sub.add_parser("stats", help="row counts and coverage")
    st.add_argument("--db", default=None)
    st.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="check every component on this machine")

    ix = sub.add_parser("index", help="embed captured text for meaning search (Stage 5)")
    ix.add_argument("--db", default=None)

    rp = sub.add_parser("replay", help="run the trigger gate over stored history (Stage 3 GO gate)")
    rp.add_argument("--since", help="'YYYY-MM-DD HH:MM' (default: all history)")
    rp.add_argument("--until", help="'YYYY-MM-DD HH:MM' (default: now)")
    rp.add_argument("--dry", action="store_true", help="Tier 1 only: list candidates, no cloud calls")
    rp.add_argument("--intent", help="pretend this focus intent held throughout (tests FOCUS)")
    rp.add_argument("--db", default=None)

    dl = sub.add_parser("deadlines", help="deadlines Jimmy found (D32); --scan looks through history")
    dl.add_argument("--scan", action="store_true", help="scan all stored text (the local model decides)")
    dl.add_argument("--dry", action="store_true", help="with --scan: list date lines only, no model, nothing saved")
    dl.add_argument("--db", default=None)

    fg = sub.add_parser("forget", help='delete a span of captures, e.g. "September" (D39); asks first')
    fg.add_argument("when", help='"September", "1 to 15 September", "older than 30 days", "today", "everything"')
    fg.add_argument("--yes", action="store_true", help="don't ask")
    fg.add_argument("--db", default=None)

    cp = sub.add_parser("compact", help="give deleted space back and tidy the search index (D39)")
    cp.add_argument("--db", default=None)

    a = ap.parse_args(argv)

    if a.cmd == "replay":
        return _replay(a)

    if a.cmd == "deadlines":
        return _deadlines(a)

    if a.cmd == "doctor":
        return _doctor()

    from .db import Store
    db = a.db or config.DB_PATH

    if a.cmd == "run":
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _instance = k32.CreateMutexW(None, False, "Local\\JimmyAmbientRun")   # held until exit
        if ctypes.get_last_error() == 183:                                    # ERROR_ALREADY_EXISTS
            print("Jimmy is already running (another `ambient run`). Quit that one first.")
            return 1
        from . import logs
        print(f"[bus] console kept in {logs.install()} (no captured text)")    # D45
        from .bus import ContextBus
        bus = ContextBus(db_path=db, monitor=a.monitor,
                         audio=not a.no_audio, thumbs=not a.no_thumbs, cards=not a.no_cards,
                         overlay=not a.no_overlay, demo=a.demo)
        counters = bus.run(duration_s=a.seconds)
        print(json.dumps(counters.as_dict(), indent=2))
        return 0

    if a.cmd == "search":
        # Keywords + meaning, within any time the query names (Stage 5, D24).
        from .plugin import time_window
        from .recall import hybrid
        w = time_window(a.query, int(time.time() * 1000))
        with Store(db) as store:
            hits = hybrid(store, a.query, w[0] if w else 0, w[1] if w else 1 << 62, a.limit)
        if not hits:
            print("no matches")
            return 1
        for h in hits:
            when = time.strftime("%a %d %b %H:%M", time.localtime(h["ts"] / 1000))
            where = h["title"] or h["app"] or f"heard near {h['source']}"
            print(f"{when}  [{h['via']}]  {(where or '')[:56]}")
            print(f"    {' '.join(h['text'].split())[:160]}")
        return 0

    if a.cmd == "index":
        from .recall import index
        t0, total = time.time(), 0
        with Store(db) as store:
            while n := index(store):
                total += n
                print(f"  embedded {total} chunks ({time.time() - t0:.0f}s)", flush=True)
        print(f"index up to date: {total} new chunks in {time.time() - t0:.1f}s")
        return 0

    if a.cmd in ("forget", "compact"):
        with Store(db) as store:
            if a.cmd == "forget":
                from .plugin import date_range
                w = date_range(a.when, int(time.time() * 1000))
                if not w:
                    print(f"no dates in {a.when!r}: try \"September\", \"1 to 15 September\", \"today\"")
                    return 1
                n = store.measure(w[0], w[1])
                fmt = lambda ms: time.strftime("%Y-%m-%d %H:%M", time.localtime(ms / 1000))  # noqa: E731
                print(f"{w[2]}: {fmt(w[0])} to {fmt(w[1])}: {n['frames']} screenshots, "
                      f"{n['speech']} lines heard, {n['bytes'] / 1e6:.0f} MB of pictures")
                if not (n["frames"] or n["speech"]):
                    return 0
                if not a.yes and input("Delete for good? [y/N] ").strip().lower() not in ("y", "yes"):
                    print("kept")
                    return 1
                print(json.dumps(store.forget(w[0], w[1])))
                from jimmy import config as jcfg
                from jimmy.memory import Memory
                mem = Memory(jcfg.MEMORY_DB)
                mem.forget_turns(w[0], w[1])
                mem.close()
            before, after = store.compact()
            print(f"database {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
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
