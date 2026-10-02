"""One runnable check for D37 ("remember my face"). `python tests/test_face.py`.
No webcam: frames are drawn, the detector and recogniser are the real models."""
from __future__ import annotations

import pickle
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ambient import config  # noqa: E402
from ambient.presence import Enrolment, OwnerFace, Presence, STEPS, Tracker, check, yaw_of  # noqa: E402


def row(x=200, y=120, w=240, h=260, yaw=0.0):
    """A YuNet-shaped detection: box, then right eye, left eye, nose, mouth corners."""
    ex1, ex2 = x + w * 0.3, x + w * 0.7
    eye = ex2 - ex1
    nx = (ex1 + ex2) / 2 + yaw * eye
    return np.array([x, y, w, h, ex1, y + h * 0.4, ex2, y + h * 0.4, nx, y + h * 0.6,
                     ex1, y + h * 0.8, ex2, y + h * 0.8, 0.95], dtype=np.float32)


def textured(lum=130):
    rng = np.random.default_rng(1)
    return np.clip(rng.normal(lum, 40, (480, 640)), 0, 255).astype(np.uint8)


def test_guidance_says_what_to_fix():
    g = textured()
    assert check([], g, 0, 0)[0].startswith("I can't see your face")
    assert check([row(), row(x=20)], g, 0, 0)[0].startswith("Just you")
    assert check([row(w=60, h=70)], g, 0, 0)[0] == "Come a little closer."
    assert check([row(x=10, w=420, h=440)], g, 0, 0)[0] == "Move back a little."
    assert check([row(x=0, y=0, w=150, h=170)], g, 0, 0)[0] == "Move into the middle of the picture."
    assert check([row()], textured(30), 0, 0)[0].startswith("It's a bit dark")
    assert check([row()], textured(240), 0, 0)[0].startswith("Too much light")
    flat = np.full((480, 640), 130, np.uint8)
    assert check([row()], flat, 0, 0)[0] == "Hold still for a moment.", "no detail = motion blur"
    assert check([row(yaw=0.3)], g, 0, 0) == (STEPS[0][0], False), "step 1 wants you looking straight"
    assert check([row()], g, 0, 0) == ("Hold it there.", True)
    assert check([row()], g, 1, 0) == (STEPS[1][0], False)
    assert check([row(yaw=0.3)], g, 1, 0)[1] and abs(yaw_of(row(yaw=0.3)) - 0.3) < 1e-4
    assert not check([row(yaw=0.3)], g, 2, 1.0)[1], "the other side means the other sign"
    assert check([row(yaw=-0.3)], g, 2, 1.0)[1]
    print("ok  guidance: closer, back, middle, light, still, straight, each side")


def test_enrolment_steps_and_consistency():
    e = Enrolment(0.0)
    base = np.random.default_rng(0).normal(size=128).astype(np.float32)
    t = 0.0
    for step, (_, n) in enumerate(STEPS):
        for _ in range(n):
            t += 0.3
            e.take(t, base + np.random.default_rng(int(t * 10)).normal(scale=0.05, size=128), 0.3 if step == 1 else -0.3)
    assert e.done and len(e.samples) == sum(n for _, n in STEPS) and e.side == 1.0
    assert e.consistent(), "the same face, straight on, agrees with itself"
    e.take(t + 0.1, base, 0)
    bad = Enrolment(0.0)
    for i in range(STEPS[0][1]):
        bad.take(i * 0.3 + 0.3, np.random.default_rng(100 + i).normal(size=128), 0)
    assert not bad.consistent(), "a blurry, mixed capture is refused, not saved"
    assert Enrolment(0.0).progress == 0.0
    print("ok  capture: steps advance, sides recorded, inconsistent captures refused")


def test_template_is_encrypted_and_forgettable():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "owner.bin"
        o = OwnerFace(path)
        assert not o.known and o.match(np.ones(128)) == 0.0
        me = np.random.default_rng(3).normal(size=128).astype(np.float32)
        o.save([me, me * 1.01])
        raw = path.read_bytes()
        assert OwnerFace.MAGIC not in raw and me.tobytes()[:16] not in raw, "DPAPI, not raw floats"
        again = OwnerFace(path)
        assert again.known and again.match(me) > 0.99
        assert again.match(np.random.default_rng(4).normal(size=128)) < config.OWNER_MATCH, "a stranger"
        for obj in (again, Presence(lambda i: None, owner=again)):
            try:
                pickle.dumps(obj)
            except TypeError:
                pass
            else:
                raise AssertionError(f"{type(obj).__name__} must refuse to be serialised")
        again.forget()
        assert not path.exists() and not again.known
    print("ok  template: DPAPI-encrypted, matches you, not others; forget deletes it")


def test_capture_end_to_end():
    """Presence._enrol_tick over a scripted sitting: the events the overlay draws,
    then exactly one save, of your vectors only."""
    events = []
    base = np.random.default_rng(7).normal(size=128).astype(np.float32)

    class FakeRec:
        def alignCrop(self, img, f):
            return f

        def feature(self, f):
            return (base + np.random.default_rng(int(f[8] * 1000)).normal(scale=0.03, size=128)).reshape(1, 128)

    with tempfile.TemporaryDirectory() as d:
        p = Presence(lambda i: None, on_enrol=events.append, owner=OwnerFace(Path(d) / "o.bin"))
        p.enrol()
        p._want_enrol, p._enrol = False, Enrolment(0.0)
        img, gray, t = np.zeros((480, 640, 3), np.uint8), textured(), 0.0
        p._enrol_tick(t, img, gray, [], FakeRec())
        assert events[-1]["say"].startswith("I can't see your face") and not events[-1]["ok"]
        assert events[-1]["preview"].startswith("data:image/jpeg;base64,") and events[-1]["box"] is None
        for yaw, n in ((0.0, 6), (0.3, 4), (-0.3, 4)):
            for i in range(n):
                t += 0.3
                p._enrol_tick(t, img, gray, [row(yaw=yaw + i * 0.001)], FakeRec())
        assert events[-1]["done"] and not events[-1]["failed"], events[-1]
        assert p.owner.known and len(p.owner.vectors) == 14 and not p.enrolling
        assert any(e.get("step") == 1 for e in events) and any(e.get("step") == 2 for e in events)
        assert all(0 <= e["box"][0] <= 1 for e in events if e.get("box")), "the box is mirrored and normalised"
        events.clear()
        p._want_enrol, p._enrol = False, Enrolment(0.0)
        p._enrol_tick(config.ENROL_TIMEOUT_S + 1, img, gray, [row()], FakeRec())
        assert events[-1]["failed"] and "too long" in events[-1]["say"], "a capture that never finishes gives up"
        assert p.forget().startswith("Forgotten") and not p.owner.known
    print("ok  capture end to end: guidance, preview, three steps, one save, timeout, forget")


def test_tracker_with_a_remembered_face():
    t = Tracker()                     # D39: who the face is, is judged per track (tests/test_stage9.py)
    assert t.update(0, True) == "present"
    t.update(1, False, stranger=True)
    assert t.update(1.5, False, stranger=True) == "present", "not yet STRANGER_S: not a stranger"
    assert t.update(1 + config.STRANGER_S, False, stranger=True) == "stranger"
    t.update(5, True)
    assert t.update(5.01 + config.RETURN_S, True) == "present", "you're back"
    t.update(9, True, others=1)
    assert t.update(9 + config.WATCHED_S, True, others=1) == "watched"
    print("ok  tracker: you, a stranger (after 2 s), you and someone")


def test_detector_on_a_drawn_face():
    """The real YuNet on a drawn face: the shapes check() reads are what it returns."""
    sys.path.insert(0, str(Path(__file__).parent))
    from test_stage1 import _synthetic_face_frame        # the faces stage 1 proves YuNet finds
    img = _synthetic_face_frame()
    det = cv2.FaceDetectorYN.create(str(config.MODELS_DIR / "face_detection_yunet_2023mar.onnx"), "",
                                    (img.shape[1], img.shape[0]), config.FACE_SCORE_THRESHOLD)
    _, faces = det.detect(img)
    assert faces is not None and len(faces) == 2 and faces.shape[1] == 15
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert check(list(faces), gray, 0, 0)[0].startswith("Just you"), "two drawn people: just you, please"
    assert all(abs(yaw_of(f)) < 0.35 for f in faces), "drawn faces look straight ahead"
    print("ok  detector: real YuNet rows feed the guidance (two faces -> 'just you')")


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
    sys.exit(1 if failed else 0)
