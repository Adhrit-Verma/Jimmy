"""One runnable check for stage 1. `python tests/test_stage1.py` -- no framework.

Covers the logic that would fail silently: the FTS wiring, the exclusion list,
the perceptual-change gate, the VAD state machine, the audio conversion, and the
two non-negotiables about faces (ephemeral, never serialisable).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ambient import screen  # noqa: E402
from ambient.audio import VadChunker, is_hallucination, to_mono16k  # noqa: E402
from ambient.db import Store  # noqa: E402
from ambient.redact import Exclusions, FaceStage, _blur_region, _cosine  # noqa: E402

RATE = 16000


def test_store_roundtrip_and_fts():
    with Store(":memory:") as s:
        wid = s.open_window("app", ts=1000)
        fid = s.add_frame(wid, "code.exe", "bus.py - Jimmy", "thumb.jpg", 0, ts=1000)
        s.add_text(fid, "uia", "the trigger gate is a cost control as much as a taste control")
        s.add_text(fid, "ocr", "unrelated pixels")
        s.add_audio(2000, 5000, "mic", "we should tune the trigger gate before stage four", wid)
        assert s.add_text(fid, "uia", "   ") is None, "blank text must not be stored"

        hits = s.search("trigger gate")
        kinds = {h["kind"] for h in hits}
        assert kinds == {"screen", "audio"}, f"FTS must span both tables, got {kinds}"
        assert any("[trigger]" in h["snippet"] for h in hits), "snippet must mark the match"

        assert s.search("nonexistentterm") == []
        st = s.stats()
        assert st["frames"] == 1 and st["text_blocks"] == 2 and st["audio_segments"] == 1

        # The deliberate absences from the schema.
        names = {r[0] for r in s.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "faces" not in names and "people" not in names, \
            "a faces/people table means the design was lost"
    print("ok  store + fts5")


def test_fts_stays_in_step_on_delete():
    with Store(":memory:") as s:
        wid = s.open_window()
        fid = s.add_frame(wid, "a.exe", "t")
        tid = s.add_text(fid, "uia", "ephemeral differentiation")
        assert s.search("ephemeral")
        s.conn.execute("DELETE FROM text_blocks WHERE id=?", (tid,))
        s.conn.commit()
        assert s.search("ephemeral") == [], "delete trigger must clear the index"
    print("ok  fts delete trigger")


def test_exclusions():
    ex = Exclusions()
    assert ex.check(app=r"C:\Program Files\1Password\1Password.exe")
    assert ex.check(app="BITWARDEN.EXE"), "exe match must be case-insensitive"
    assert ex.check(title="Inbox - Google Chrome (Incognito)")
    assert ex.check(title="InPrivate - Microsoft Edge")
    assert ex.check(url="https://netbanking.hdfcbank.com/netbanking/")
    assert ex.check(url="https://www.onlinesbi.sbi/")
    assert ex.check(app="code.exe", title="bus.py - Jimmy") is None, "normal work must pass"
    assert ex.check(url="https://docs.python.org/3/library/sqlite3.html") is None

    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "exclusions.txt"
        f.write_text("# mine\nexe:mysecret.exe\ntitle:payroll\nurl:[unclosed\n", encoding="utf-8")
        ex2 = Exclusions(f)
        assert ex2.check(app="mysecret.exe") and ex2.check(title="Q3 PAYROLL sheet")
        assert ex2.check(app="code.exe", title="bus.py") is None, \
            "a bad user regex must be skipped, not fatal"
    print("ok  exclusions")


def _chat_screen(offset: int = 0):
    """A dark-theme chat at screen size: the case the old dhash gate missed."""
    import cv2
    img = np.full((1080, 1920, 3), 38, np.uint8)
    img[:, :300] = 30                                   # sidebar
    for i in range(40):
        y = 140 + i * 60 - offset
        if 120 < y < 1000:
            cv2.putText(img, f"user{i % 3}: message number {i} about the gate and the replay",
                        (340, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 220, 220), 2)
    return img


def test_change_gate():
    from ambient import config
    a = _chat_screen()
    sig = screen.signature(a)
    assert screen.changed_pct(sig, screen.signature(a.copy())) == 0

    scrolled = screen.changed_pct(sig, screen.signature(_chat_screen(offset=60)))
    assert scrolled >= config.GATE_CHANGED_PCT, \
        f"one chat message of scroll must count as a change ({scrolled:.2f}%)"

    cur = a.copy()
    cur[600:622, 900:902] = 255                        # a text cursor blinking
    blink = screen.changed_pct(sig, screen.signature(cur))
    assert blink < config.GATE_CHANGED_PCT, f"a cursor blink must not ({blink:.2f}%)"
    print(f"ok  change gate (scroll {scrolled:.1f}%, cursor {blink:.2f}%)")


def test_only_new_lines_are_stored():
    from ambient.bus import new_lines
    seen: set[str] = set()
    assert new_lines("Inbox\nhello there\nhow are you", seen) == "Inbox\nhello there\nhow are you"
    assert new_lines("Inbox\nhello there\nhow are you", seen) == "", "an unchanged screen stores nothing"
    assert new_lines("Inbox\nhow are you\nsee you at 3", seen) == "see you at 3", "only the new line"
    assert new_lines("  \n\n", set()) == ""
    print("ok  only new lines stored")


def test_face_stage_is_ephemeral():
    fs = FaceStage()
    v = np.ones((1, 128), dtype=np.float32)
    fs._vectors["win-a"] = [v]
    fs._vectors["win-b"] = [v]

    assert fs.tracked("win-a") == 1
    fs.close_window("win-a")
    assert fs.tracked("win-a") == 0, "closing a window must drop its vectors"
    assert fs.tracked("win-b") == 1, "other windows are untouched"
    fs.reset()
    assert fs._vectors == {}

    for dump in (lambda: __import__("pickle").dumps(fs), fs.__getstate__):
        try:
            dump()
        except TypeError:
            pass
        else:
            raise AssertionError("FaceStage must refuse to serialise")

    assert abs(_cosine(v, v) - 1.0) < 1e-6
    assert abs(_cosine(v, -v) + 1.0) < 1e-6
    assert _cosine(v, np.zeros_like(v)) == 0.0
    print("ok  face stage ephemerality")


def test_capture_window_lifecycle():
    """Alt-tabbing must not shred capture windows -- that was the first bug here."""
    import time as _time

    from ambient import config
    from ambient.bus import ContextBus, Counters

    b = ContextBus.__new__(ContextBus)  # skip __init__: no DXGI device needed
    b.store, b.faces, b.counters, b._open, b.window_id = Store(":memory:"), FaceStage(), Counters(), {}, None

    a1 = b._window_for("code.exe", 1000)
    a2 = b._window_for("code.exe", 1002)
    assert a1.id == a2.id, "staying in one app must reuse its window"

    c1 = b._window_for("chrome.exe", 1004)
    assert c1.id != a1.id, "a different app gets its own window"
    assert b._window_for("code.exe", 1006).id == a1.id, \
        "coming back within the grace period must reuse the original window"
    assert b.counters.windows == 2

    # Faces are keyed by window, so an alive window keeps them.
    b.faces._vectors[a1.id] = [np.ones((1, 128), dtype=np.float32)]

    idle, b_max = config.WINDOW_IDLE_S, config.WINDOW_MAX_S
    try:
        config.WINDOW_IDLE_S = 0.01
        _time.sleep(0.05)
        b._window_for("chrome.exe", 1008)  # expires anything untouched
        assert "code.exe" not in b._open, "an app left alone must have its window closed"
        assert b.faces.tracked(a1.id) == 0, "closing a window must forget its faces"
        row = b.store.conn.execute(
            "SELECT closed_at FROM capture_windows WHERE id=?", (a1.id,)).fetchone()
        assert row[0] is not None, "the closed window must be stamped in the db"
    finally:
        config.WINDOW_IDLE_S, config.WINDOW_MAX_S = idle, b_max
    b.store.close()
    print("ok  capture window lifecycle")


def _synthetic_face_frame():
    """A frame with faces YuNet will actually find, so redaction can be proven."""
    import cv2
    img = np.full((720, 1280, 3), 235, np.uint8)

    def face(cx, cy, s, skin):
        cv2.ellipse(img, (cx, cy), (int(s * .72), s), 0, 0, 360, skin, -1)
        for dx in (-1, 1):
            ex, ey = cx + dx * int(s * .30), cy - int(s * .18)
            cv2.ellipse(img, (ex, ey), (int(s * .17), int(s * .10)), 0, 0, 360, (250, 250, 250), -1)
            cv2.circle(img, (ex, ey), max(2, int(s * .07)), (40, 30, 25), -1)
            cv2.ellipse(img, (ex, ey - int(s * .16)), (int(s * .19), int(s * .07)), 0, 180, 360,
                        (45, 35, 30), 3)
        cv2.ellipse(img, (cx, cy + int(s * .06)), (int(s * .07), int(s * .16)), 0, 0, 360,
                    tuple(int(v * .88) for v in skin), -1)
        cv2.ellipse(img, (cx, cy + int(s * .42)), (int(s * .26), int(s * .12)), 0, 0, 180,
                    (90, 70, 95), -1)

    face(330, 380, 130, (185, 200, 225))
    face(930, 380, 160, (150, 170, 205))
    return img


def test_blur_defeats_redetection():
    """The acceptance criterion: no unblurred face reaches disk.

    Weaker settings passed a visual glance and still failed this -- the detector
    found the face again in the saved artifact. Assert the detector, not the eye.
    """
    import cv2
    fs = FaceStage()
    if not fs.available:
        print("skip  blur redetection (face models missing)")
        return
    src = _synthetic_face_frame()
    blurred, count, _ = fs.process(src, "w1")
    assert count >= 1, "the fixture must contain a detectable face or this proves nothing"

    _, again, _ = fs.process(blurred, "w2")
    assert again == 0, f"{again} face(s) still findable after blurring"

    # What actually lands on disk is a JPEG; compression must not resurrect anything.
    ok, enc = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, 70])
    assert ok
    _, after_jpeg, _ = fs.process(cv2.imdecode(enc, cv2.IMREAD_COLOR), "w3")
    assert after_jpeg == 0, f"{after_jpeg} face(s) findable after the jpeg round-trip"

    assert not np.array_equal(src, blurred), "the source frame must not be returned unchanged"
    print(f"ok  blur defeats redetection ({count} faces in, 0 out)")


def test_process_does_not_mutate_source():
    fs = FaceStage()
    if not fs.available:
        print("skip  non-mutation (face models missing)")
        return
    src = _synthetic_face_frame()
    keep = src.copy()
    fs.process(src, "w1")
    assert np.array_equal(src, keep), \
        "process must not blur in place; callers still need the clean frame in memory"
    print("ok  process leaves the source frame alone")


def test_blur_destroys_detail():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    before = img[60:140, 60:140].copy()
    _blur_region(img, 60, 60, 80, 80)
    after = img[60:140, 60:140]
    assert float(after.std()) < float(before.std()) / 2, "blur must remove detail, not shuffle it"
    assert not np.array_equal(before, after)

    flat = np.zeros((50, 50, 3), dtype=np.uint8)
    _blur_region(flat, -10, -10, 5, 5)          # off-canvas must not raise
    _blur_region(flat, 45, 45, 200, 200)        # oversized must clamp
    print("ok  blur")


class _ScriptedVad:
    def __init__(self, pattern): self.pattern, self.i = pattern, 0
    def is_speech(self, *_):
        v = self.pattern[min(self.i, len(self.pattern) - 1)]
        self.i += 1
        return v


def test_vad_chunker_state_machine():
    ch = VadChunker("mic", silence_ms=90, min_ms=100, max_ms=100000)
    # 3 quiet, 10 speech, 4 quiet (silence_ms=90 -> 3 frames closes it)
    ch.vad = _ScriptedVad([False] * 3 + [True] * 10 + [False] * 4 + [False] * 50)
    pcm = np.zeros(ch.frame_len * 17, dtype=np.int16)
    segs = ch.push(pcm, 10_000)
    assert len(segs) == 1, f"one utterance -> one segment, got {len(segs)}"
    seg = segs[0]
    assert seg.source == "mic" and seg.ts_start < 10_000 + 3 * ch.frame_ms, \
        "pre-roll must start the segment before the first voiced frame"
    assert seg.ts_end > seg.ts_start and len(seg.pcm) > 0

    quiet = VadChunker("mic")
    quiet.vad = _ScriptedVad([False])
    assert quiet.push(np.zeros(quiet.frame_len * 40, dtype=np.int16), 0) == []
    assert quiet.flush() == [], "silence must never produce a segment"

    short = VadChunker("mic", silence_ms=60, min_ms=5000)
    short.vad = _ScriptedVad([True] * 2 + [False] * 10)
    assert short.push(np.zeros(short.frame_len * 12, dtype=np.int16), 0) == [], \
        "a cough shorter than min_ms must be dropped"
    print("ok  vad chunker")


def test_hallucination_filter():
    # Measured on this machine: silence decoded as "you", white noise as "Thanks."
    for junk in ("you", "Thanks.", "Thank you.", "  BYE  ", "...", "Please subscribe", ""):
        assert is_hallucination(junk), f"{junk!r} must be dropped"
    for real in ("thanks for pushing the fix",
                 "you should tune the gate first",
                 "bye for now, I will check the replay tomorrow"):
        assert not is_hallucination(real), f"{real!r} is a real utterance"
    print("ok  hallucination filter")


def test_mic_pauses_on_sensitive_surface_unless_call():
    """D9: a spoken OTP on a bank page is not transcribed; a call is not dropped."""
    import threading

    from ambient import audio, screen as scr
    from ambient.bus import ContextBus, Counters

    class FakeSource:
        def grab(self, *_):
            return np.random.default_rng().integers(0, 255, (120, 160, 3), dtype=np.uint8)

    class FakeAudio:
        paused = threading.Event()

    b = ContextBus.__new__(ContextBus)
    b.store, b.faces, b.counters, b._open, b.window_id = Store(":memory:"), FaceStage(), Counters(), {}, None
    b.exclusions, b.source, b.want_thumbs = Exclusions(), FakeSource(), False
    b._sensitive_key, b._sensitive_reason, b._audio, b.gate = None, "", FakeAudio(), None

    page = {"title": "Account - Chrome", "url": "https://netbanking.hdfcbank.com/"}
    call = {"on": False}
    saved = (scr.active_window, scr.window_text, audio.other_app_using_mic)
    scr.active_window = lambda: scr.ActiveWindow(42, "chrome.exe", page["title"])
    scr.window_text = lambda hwnd: scr.WindowText("balance", page["url"], 1, 0.0, False)
    audio.other_app_using_mic = lambda: call["on"]
    try:
        assert b.tick() == "excluded" and b._audio.paused.is_set(), "bank page must pause the mic"

        b._open["chrome.exe"].last_sig = None
        assert b.tick() == "excluded" and b._audio.paused.is_set(), \
            "the same page must stay excluded without re-walking it"

        call["on"] = True
        b.tick()
        assert not b._audio.paused.is_set(), "a call in progress must keep recording"

        call["on"] = False
        page.update(title="Docs - Chrome", url="https://docs.python.org/")
        assert b.tick() == "captured" and not b._audio.paused.is_set(), "leaving the bank resumes"
    finally:
        scr.active_window, scr.window_text, audio.other_app_using_mic = saved
        b.store.close()

    ch = VadChunker("mic", silence_ms=90, min_ms=10)
    ch.vad = _ScriptedVad([True] * 50)
    ch.push(np.zeros(ch.frame_len * 5, dtype=np.int16), 0)
    ch.reset()
    assert ch.flush() == [], "reset must drop the half-finished utterance"
    assert isinstance(audio.other_app_using_mic(), bool), "the registry probe must not raise"
    print("ok  mic pauses on sensitive surfaces unless a call is on")


def test_silence_watch():
    from ambient.audio import SilenceWatch
    w = SilenceWatch(after_s=60, floor=120)
    assert w.feed(3, 0) is None and w.feed(3, 59) is None, "quiet, but not for long yet"
    note = w.feed(3, 61)
    assert note and "min" in note, "a long quiet stretch must be said out loud"
    assert w.feed(3, 500) is None, "only once per quiet stretch"
    assert w.feed(2000, 501) == "sound is back"
    assert w.feed(2000, 502) is None
    print("ok  silence watch")


def test_audio_conversion():
    stereo48 = np.zeros((480 * 2,), dtype=np.int16)
    stereo48[0::2] = 1000   # left
    stereo48[1::2] = 2000   # right
    mono = to_mono16k(stereo48.tobytes(), 48000, 2)
    assert len(mono) == 160, f"480 stereo frames @48k -> 160 mono @16k, got {len(mono)}"
    assert abs(int(mono[5]) - 1500) <= 1, "channels must be averaged, not dropped"

    assert len(to_mono16k(np.zeros(320, dtype=np.int16).tobytes(), 16000, 1)) == 320
    odd = to_mono16k(np.zeros(441, dtype=np.int16).tobytes(), 44100, 1)
    assert abs(len(odd) - 160) <= 2, f"non-integer ratio must still resample, got {len(odd)}"
    print("ok  audio conversion")


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
