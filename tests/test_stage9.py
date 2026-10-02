"""One runnable check for D39: the curtain that follows you, talking to Jimmy without
its name, the database kept small, and timers. `python tests/test_stage9.py`.
No webcam, no network, no Electron: scenes are drawn, the model is faked."""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ambient import config  # noqa: E402
from ambient.presence import Follow, Gaze, Presence, Tracker, irises, mouth_of  # noqa: E402
from test_face import row  # noqa: E402

FACE = row(235, 90, 170, 220)           # where the drawn person's face is


def room(seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = cv2.GaussianBlur(np.clip(rng.normal(150, 25, (480, 640)), 0, 255).astype(np.uint8), (0, 0), 3)
    cv2.rectangle(img, (40, 60), (180, 300), 90, -1)          # a shelf
    cv2.rectangle(img, (470, 40), (600, 200), 200, -1)        # a window
    cv2.rectangle(img, (220, 230), (430, 480), 60, -1)        # the chair
    return img


def person(img: np.ndarray, dx: int = 0, turned: bool = False, down: bool = False) -> np.ndarray:
    """Someone in the chair: shoulders, neck, head; turned = the back of the head."""
    img = img.copy()
    cx, cy = 320 + dx, 200 + (25 if down else 0)
    cv2.ellipse(img, (320 + dx, 470), (190, 130), 0, 180, 360, 110, -1)
    cv2.rectangle(img, (295 + dx, 270), (345 + dx, 360), 170, -1)
    cv2.ellipse(img, (cx, cy), (85, 110), 0, 0, 360, 175, -1)
    cv2.ellipse(img, (cx - (30 if turned else 0), cy - 40), (90, 75), 0, 180, 360, 40, -1)
    if turned:
        cv2.ellipse(img, (cx - 40, cy + 10), (60, 100), 0, 0, 360, 45, -1)
    else:
        for ex in (-30, 30):
            cv2.circle(img, (cx + ex, cy - 10), 8, 50, -1)
        cv2.ellipse(img, (cx, cy + 50), (25, 8), 0, 0, 360, 90, -1)
    return img


def frames(p: Presence, tracker: Tracker, t: float, gray: np.ndarray, faces: list, rec=None,
           until: float | None = None, step: float = 0.25) -> tuple[str, float]:
    """Feed the same picture from t to `until`, 4 a second; the last state and time."""
    small = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    state = tracker.state
    while True:
        state = p.observe(t, small, gray, faces, rec, tracker)
        if until is None or t >= until:
            return state, t
        t += step


class _Nobody:
    """No face remembered (never the real data/owner_face.bin)."""
    known = False


def test_curtain_follows_you_not_your_eyes():
    p, tr = Presence(lambda i: None, owner=_Nobody()), Tracker()
    here, turned, down, chair = person(room()), person(room(), turned=True), person(room(), down=True), room()
    st, t = frames(p, tr, 0, here, [FACE], until=1)
    assert st == "present" and p.track is not None, "your face is found and marked"
    st, t = frames(p, tr, t + 0.25, turned, [], until=t + 30)
    assert st == "present", "head turned away for 30 s, face not found: still you (followed)"
    st, t = frames(p, tr, t + 0.25, down, [], until=t + 30)
    assert st == "present", "looking down: still you"
    left = t + 0.25
    st, t = frames(p, tr, left, chair, [], until=left + config.AWAY_S + 0.5)
    assert st == "away" and p.track is None, f"you left: curtain within {config.AWAY_S + 0.5} s"
    st, t = frames(p, tr, t + 0.25, person(room(), turned=True), [], until=t + 5)
    assert st == "away", "someone not facing the screen doesn't lift it"
    st, t = frames(p, tr, t + 0.25, here, [FACE], until=t + config.RETURN_S + 0.5)
    assert st == "present", "back, facing the screen: lifted"
    # The template is never refreshed while blind, so it can't learn the empty chair...
    f = Follow(FACE, cv2.resize(here, (160, 120), interpolation=cv2.INTER_AREA), 0.0)
    q = lambda g: cv2.resize(g, (160, 120), interpolation=cv2.INTER_AREA)  # noqa: E731
    assert f.find(q(turned), 1) >= config.FOLLOW_MIN > f.find(q(chair), 2), "turned head kept, chair not"
    assert f.find(q(here), config.BLIND_MAX_S + 1) == 0.0, "...and with no face for BLIND_MAX_S it stops trusting it"
    for obj in (p, f, Gaze()):
        try:
            pickle.dumps(obj)
        except TypeError:
            continue
        raise AssertionError(f"{type(obj).__name__} must refuse to be serialised")
    print(f"ok  curtain: turned head and looking down keep you; leaving curtains in {config.AWAY_S} s; back lifts")


class _Owner:
    known = True

    def match(self, feat) -> float:
        return float(feat[0])


class _Rec:
    """SFace stand-in: the 'feature' of a face is its match score, set per test."""
    def __init__(self):
        self.score = {}

    def alignCrop(self, img, f):
        return f

    def feature(self, f):
        return np.array([self.score.get(int(f[0]), 0.0)], dtype=np.float32)


def test_identity_once_per_track():
    rec, here = _Rec(), person(room())
    p, tr = Presence(lambda i: None, owner=_Owner()), Tracker()
    rec.score[235] = 0.6
    st, t = frames(p, tr, 0, here, [FACE], rec, until=1)
    assert st == "present" and p.track.owner is True
    rec.score[235] = 0.1                                 # dim light: a bad match...
    st, t = frames(p, tr, t + 0.25, here, [FACE], rec, until=t + config.REVERIFY_S - 1)
    assert st == "present", "...doesn't drop the curtain on you: identity isn't re-judged every frame"
    st, t = frames(p, tr, t + 0.25, here, [FACE], rec, until=t + 2 * config.REVERIFY_S + config.STRANGER_S + 1)
    assert st == "stranger", "two re-checks below OWNER_KEEP: not you after all"

    p, tr = Presence(lambda i: None, owner=_Owner()), Tracker()
    rec.score[235] = 0.1
    st, t = frames(p, tr, 0, here, [FACE], rec, until=0.5)
    assert st == "present" and p.track.owner is None, "still judging: no verdict from one look"
    st, t = frames(p, tr, t + 0.25, here, [FACE], rec, until=t + config.ID_TRIES * config.ID_EVERY_S
                   + config.STRANGER_S + 0.5)
    assert st == "stranger", "someone else at the screen: curtain"
    rec.score[235] = 0.6
    st, t = frames(p, tr, t + 0.25, here, [FACE], rec, until=t + 2 + config.RETURN_S + 0.5)
    assert st == "present", "a later good look at you lifts it: one bad capture doesn't lock you out"
    print("ok  identity: judged when a face appears, re-checked every 15 s, never flapping per frame")


def eye_img(iris_dx: float = 0.0, iris_dy: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    g = np.full((480, 640), 170, np.uint8)
    r = row(200, 100, 240, 260)
    d = float(r[6] - r[4])
    for i in (4, 6):
        ex, ey = float(r[i]), float(r[i + 1])
        cv2.ellipse(g, (int(ex), int(ey)), (int(0.2 * d), int(0.09 * d)), 0, 0, 360, 235, -1)
        cv2.circle(g, (int(ex + iris_dx * d), int(ey + iris_dy * d)), int(0.07 * d), 40, -1)
    return g, r


def test_eyes_and_lips():
    g, r = eye_img()
    cx, cy = irises(g, r)
    assert abs(cx) < 0.02 and abs(cy) < 0.02, (cx, cy)
    g2, _ = eye_img(0.08, -0.04)
    x2, y2 = irises(g2, r)
    assert x2 > cx + 0.04 and y2 < cy - 0.015, "irises moved right and up: the estimate follows"
    still = mouth_of(g, r)
    assert float(np.abs(mouth_of(g, r) - still).mean()) < config.MOUTH_MOVING, "a still mouth isn't moving"
    open_ = g.copy()
    cv2.ellipse(open_, (int((r[10] + r[12]) / 2), int(r[11]) + 8), (30, 18), 0, 0, 360, 30, -1)
    assert float(np.abs(mouth_of(open_, r) - still).mean()) >= config.MOUTH_MOVING, "an opened mouth is"
    gz = Gaze()
    for i in range(config.GAZE_LEARN_N + 5):           # learning: you at the screen, irises near centre
        assert gz.contact(r, (0.005 * (i % 3), 0.004 * (i % 2)))
    assert gz.contact(r, (0.005, 0.0)), "your usual place: eye contact"
    assert not gz.contact(r, (0.0, 0.12)), "eyes well down (a phone in your lap): no eye contact"
    assert not gz.contact(row(yaw=0.5), (0.0, 0.0)), "head turned: no eye contact"
    print("ok  eyes and lips: iris estimate, mouth movement, a learnt 'at the screen' zone")


def test_what_the_camera_saw_while_you_spoke():
    p = Presence(lambda i: None, owner=_Nobody())
    for i in range(20):                                # 5 s: facing, eye contact, lips moving from 2 s
        ts = 1_000_000 + i * 250
        p.history.append((ts, True, ts >= 1_002_000, True))
    assert p.spoke(1_002_000, 1_004_000) and not p.spoke(1_000_000, 1_001_500)
    assert p.eye_contact(1_002_000, 1_004_000) and p.facing_during(1_002_000, 1_004_000)
    assert p.spoke(9_000_000, 9_001_000) is None, "no frames then: can't tell"
    print("ok  presence history: lips, eye contact and facing, checked against a spoken line")


def test_the_loop_itself_with_a_fake_camera():
    """The real presence thread, camera and detector faked: you, then the empty chair,
    then you again. The resting mode (one look a second, more on motion) runs too."""
    import time
    from types import SimpleNamespace

    import ambient.audio
    import ambient.presence as pres
    here, chair, t0 = person(room()), room(), time.monotonic()
    script = lambda: here if (time.monotonic() - t0) < 1.5 or (time.monotonic() - t0) > 5 else chair  # noqa: E731

    class Cap:
        def __init__(self, *a):
            pass

        def isOpened(self):
            return True

        def set(self, *a):
            return True

        def read(self):
            return True, cv2.cvtColor(script(), cv2.COLOR_GRAY2BGR)

        def release(self):
            pass

    class Det:
        def setInputSize(self, *a):
            pass

        def detect(self, img):
            return 1, (np.array([FACE]) if int(img[200, 320, 0]) == 175 else None)

    class Cv:
        VideoCapture = Cap
        FaceDetectorYN = SimpleNamespace(create=lambda *a: Det())

        def __getattr__(self, name):
            return getattr(cv2, name)

    states, real_cv, real_busy = [], pres.cv2, ambient.audio.other_app_using
    pres.cv2, ambient.audio.other_app_using = Cv(), lambda c: False
    try:
        p = Presence(lambda i: states.append(i["state"]) if not states or states[-1] != i["state"] else None,
                     owner=_Nobody()).start()
        time.sleep(7.5)
        p.stop()
        time.sleep(0.5)
    finally:
        pres.cv2, ambient.audio.other_app_using = real_cv, real_busy
    assert states[:3] == ["present", "away", "present"], states
    print("ok  the presence thread: you, gone (curtain), back (resting mode finds you), no errors")


# --- talking to Jimmy ---------------------------------------------------------------

import ambient.ask as ask_mod  # noqa: E402
from ambient.db import Store  # noqa: E402
from datetime import datetime  # noqa: E402

NOW = int(datetime(2026, 10, 2, 15, 0).timestamp() * 1000)


class _Jim:
    class llm:
        configured = False


def asker(**acts):
    events, spoken, clock = [], [], [NOW]
    ask_mod.now_ms = lambda: clock[0]
    a = ask_mod.Asker(Store(":memory:"), events.append, speak=spoken.append, jimmy=_Jim(),
                      actions={"state": lambda: {}, **acts})

    def hear(text, t0=None):
        events.clear()
        took = a.hear(clock[0], "mic", text, t0 or clock[0] - 2000)
        assert a.wait_idle(10)
        return took
    return a, hear, spoken, clock


def test_the_name_where_whisper_put_it():
    """The first real session's misses (2026-10-02), as Whisper wrote them."""
    p = ask_mod.parse_wake
    assert p("okay hey jimmy") == "" and p("Okay, hey Jimmy Jimmy") == "Jimmy"
    assert p("take it jimmy what's on my screen") == "what's on my screen"
    assert p("One second, Jimmy turn on privacy curtain.") == "turn on privacy curtain"
    assert p("Can you, Jimmy can you go to the last month") == "can you go to the last month"
    assert p("Chime, can you tell me last time I used Discord?") == "can you tell me last time I used Discord"
    assert p("जिमी को टेस्ट कर रहा था") is None, "about Jimmy, in Hindi, isn't to Jimmy"
    assert p("I was testing Jimmy yesterday") is None and p("hey did you see jimmy") is None
    print("ok  wake word: up to three words before the name, Whisper's 'Chime', not 'about Jimmy'")


def test_a_conversation_without_the_name():
    a, hear, spoken, clock = asker()
    assert hear("Jimmy, what can you do")
    assert a.followup_until > clock[0], "answered aloud: listening on"
    a.voice_done()                                        # Jimmy's voice stops
    clock[0] += 4000
    assert hear("and how do I set a reminder"), "the next line needs no name"
    a.voice_done()
    clock[0] += 3000
    assert not hear("okay thanks") and a.followup_until == 0, "'okay thanks' ends it"
    clock[0] += 3000
    assert not hear("what time is it"), "...and after that, the name again"

    a, hear, _, clock = asker(spoke=lambda t0, t1: False)
    hear("Jimmy, what can you do")
    a.voice_done()
    assert not hear("what is this then"), "the camera saw your lips still: a video or someone else"
    a, hear, _, clock = asker(on_call=lambda: True)
    hear("Jimmy, what can you do")
    a.voice_done()
    assert not hear("and what else"), "on a call, speech is for the call"
    a, hear, _, clock = asker(facing=lambda t0, t1: False)
    hear("Jimmy, what can you do")
    a.voice_done()
    assert not hear("and what else"), "turned to someone else: not a follow-up"
    print("ok  conversation: go on without the name after an answer; 'thanks' ends it; calls and others don't count")


def test_eye_contact_means_you_mean_jimmy():
    looking = dict(spoke=lambda t0, t1: True, eye_contact=lambda t0, t1: True)
    a, hear, _, clock = asker(**looking)
    assert hear("what's on my screen"), "looking at the screen, lips moving, a question: for Jimmy"
    clock[0] += 60_000
    a.followup_until = 0
    assert not hear("I'm going to make some tea"), "a statement isn't a request, eye contact or not"
    assert hear("क्या मेरा स्क्रीन दिख रहा है"), "a Hindi question works too"
    a, hear, _, clock = asker(**{**looking, "eye_contact": lambda t0, t1: False})
    assert not hear("what's on my screen"), "looking elsewhere: say the name"
    a, hear, _, clock = asker(**{**looking, "eyes_on": lambda: False})
    assert not hear("what's on my screen"), "'only answer to your name': off"
    spoke = [False]
    a, hear, _, clock = asker(spoke=lambda t0, t1: spoke[0], eye_contact=lambda t0, t1: True)
    assert not hear("what are you doing tonight"), "someone else talking (your lips still)..."
    spoke[0] = True
    clock[0] += 5000
    assert not hear("what's on my screen"), "...means a conversation's on: eye contact alone isn't enough"
    clock[0] += ask_mod.config.OTHERS_QUIET_S * 1000
    assert hear("what's on my screen"), "quiet again: it is"
    print("ok  eye contact: looking + lips + a request = no name; statements, others talking, 'name only' don't")


def test_timers():
    rem = []
    acts = dict(remind=lambda what, due, app: rem.append({"id": len(rem) + 1, "text": what, "due_ts": due}),
                reminders=lambda: [r for r in rem if not r.get("x")],
                cancel_reminder=lambda rid: rem[rid - 1].update(x=1))
    a, hear, spoken, clock = asker(**acts)
    hear("Jimmy, set a timer for 5 minutes")
    assert rem[-1]["text"] == "5 min timer" and rem[-1]["due_ts"] == NOW + 300_000 and spoken[-1] == "Timer set: 5 min."
    hear("Jimmy, 10 minute timer to check the oven")
    assert rem[-1]["text"] == "check the oven, 10 min timer" and rem[-1]["due_ts"] == NOW + 600_000
    hear("Jimmy timer for 1 hour 30 minutes")
    assert rem[-1]["due_ts"] == NOW + 5_400_000 and rem[-1]["text"] == "1 h 30 min timer"
    clock[0] += 60_000
    hear("Jimmy how much time is left")
    assert spoken[-1].startswith("4 min left on 5 min timer"), spoken[-1]
    hear("Jimmy cancel the timer")
    assert spoken[-1] == "3 timers cancelled." and all(r.get("x") for r in rem)
    hear("Jimmy set a timer")
    assert spoken[-1].startswith("How long?")
    print("ok  timers: set, with a purpose, hours and minutes, time left, cancel")


def _db_with_a_month(tmp: Path) -> Store:
    s = Store(tmp / "ambient.db")
    for day in (15, 20, 30):                               # September, and one day in October
        for mon in (9, 10):
            ts = int(datetime(2026, mon, day if mon == 9 else 1, 12).timestamp() * 1000)
            w = s.open_window(ts=ts)
            rel = Path("thumbs") / f"{mon}{day}" / f"{ts}.jpg"
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_bytes(b"x" * 1000)
            f = s.add_frame(w, "chrome.exe", f"page {mon}-{day}", thumb_path=str(rel), ts=ts)
            b = s.add_text(f, "uia", f"zebracorn notes {mon}-{day}")
            a = s.add_audio(ts, ts + 1000, "mic", f"zebracorn said {mon}-{day}", window_id=w)
            s.add_embeddings([(b, ts, "m", "c", b"v"), (-a, ts, "m", "c", b"v")])
            s.close_window(w, ts + 5000)
    return s


def _forget_checks(s: Store, tmp: Path) -> None:
    """Delete September through the Asker, as said; check what went and what stayed."""
    from ambient.plugin import date_range
    since, until, label = date_range("everything from September", NOW)
    assert label == "September 2026"
    assert s.measure(since, until) == {"frames": 3, "speech": 3, "bytes": 3000}
    did = []
    a, hear, spoken, clock = asker(measure=s.measure,
                                   forget=lambda *w: did.append(w) or s.forget(w[0], w[1]) and "Deleted.")
    hear("Jimmy delete everything from September")
    assert "3 screenshots and 3 lines heard from September 2026" in spoken[-1] and not did, "asks first"
    hear("yes")
    assert did and did[0][:2] == (since, until), "a plain yes, right after, does it"
    n = lambda sql: s.conn.execute(sql).fetchone()[0]  # noqa: E731
    assert n("SELECT COUNT(*) FROM frames") == 3 and n("SELECT COUNT(*) FROM audio_segments") == 3
    assert n("SELECT COUNT(*) FROM embeddings") == 6, "September's vectors gone, October's stay"
    hits = s.search("zebracorn")
    assert len(hits) == 6 and all(h["ts"] >= until for h in hits), "search no longer finds September"
    assert not list((tmp / "thumbs").glob("9*")), "September's pictures are gone, folders too"
    assert len(list((tmp / "thumbs").rglob("*.jpg"))) == 3
    before, after = s.compact()
    assert after <= before


def test_forget_a_month_and_compact():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        s = _db_with_a_month(tmp)
        try:
            _forget_checks(s, tmp)
        finally:
            s.close()
    print("ok  forget: 'delete everything from September' asks, deletes rows, vectors, pictures; compacts")


def test_date_spans():
    from ambient.plugin import date_range
    day = lambda ms: datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")  # noqa: E731
    cases = {"from September September complete delete": ("2026-09-01", "2026-10-01", "September 2026"),
             "from 1 to 15 September": ("2026-09-01", "2026-09-16", "1 Sep 2026 to 15 Sep 2026"),
             "25 Sep": ("2026-09-25", "2026-09-26", "25 Sep 2026"), "November": ("2025-11-01", "2025-12-01", None),
             "since August": ("2026-08-01", "2026-10-02", "since August 2026"),
             "yesterday": ("2026-10-01", "2026-10-02", "yesterday")}
    for text, (a, b, label) in cases.items():
        got = date_range(text, NOW)
        assert (day(got[0]), day(got[1])) == (a, b) and (label is None or got[2] == label), (text, got)
    assert date_range("older than 30 days", NOW)[0] == 0 and date_range("may I ask", NOW) is None
    print("ok  spans: months, day ranges, a month said twice, since, older than, 'may' the word")


def test_resting_while_away():
    from ambient.bus import ContextBus
    from ambient.proactive import Proactive
    b = ContextBus.__new__(ContextBus)
    b._api, b._curtain, b._manual_curtain, b._sensitive, b._audio = None, False, False, False, None
    b._presence = {"state": "present"}
    b._on_presence({"state": "away", "why": ""})
    assert b._curtain and b.dormant() and b._dormant_since is not None, "away: curtain, and Jimmy rests"
    b._on_presence({"state": "present", "why": ""})
    assert not b.dormant() and b._dormant_since is None, "back: awake"
    b.set_curtain(True)
    assert not b.dormant(), "a curtain you drew keeps Jimmy listening"
    shown = []

    class Mem:
        def due_reminders(self, now, app=None):
            return [{"id": 1, "text": "5 min timer"}]

        def set_reminder_state(self, *a):
            pass
    p = Proactive(Store(":memory:"), Mem(), lambda *c: shown.append(c), say=shown.append)
    p.tick(NOW, quiet=True)
    assert shown[0][0] == "REMIND" and shown[1] == "Time's up: 5 min timer." and "minute" not in p._last
    print("ok  away: Jimmy rests (no capture, mic, indexing, own cards); timers still ring")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
