"""Presence from your own webcam, for the privacy curtain (D34, D37, D39).

It finds your face once, marks where you are, and follows that place (D39): a
turned head, looking down or away keeps you "present"; only leaving the picture
brings the curtain, within AWAY_S. While you're away it looks every few seconds,
or at once when the picture moves. Two modes:

- **Nothing remembered** (the default): it recognises no one. "present" is any
  one face that sat down facing the screen, followed from then on.
- **"Jimmy, remember my face"** (D37, the one exception to non-negotiable 2,
  made by the human on 2026-10-02): a guided capture turns *your* face into a
  template: a few SFace vectors, no image, stored encrypted with Windows DPAPI
  so only your Windows account can read it. Then "present" means you, and
  someone else alone at the screen is "stranger". A new face is judged when it
  appears and re-checked now and then, not every frame. Every other face's
  vector exists for one comparison inside one loop iteration and is dropped:
  never stored, never logged, never compared with anything but your template.
  "Jimmy, forget my face" deletes the template.

D39, for talking to Jimmy without its name: for *your* face only, whether you're
looking at the screen (head pose and irises against where you usually look,
learnt as you work) and whether your lips are moving. Kept as per-frame yes/no
values for two minutes, in RAM, so a spoken line can be checked against them.

States: present / away / watched (you and someone else) / stranger / off.
Nothing here is ever serialised; no frame outlives its tick.
"""
from __future__ import annotations

import base64
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import config
from .redact import SFACE, YUNET


def yaw_of(row) -> float:
    """Head turn from YuNet's landmarks: 0 facing the camera, about ±0.5 turned well away."""
    rx, lx, nx = float(row[4]), float(row[6]), float(row[8])
    eye = abs(lx - rx)
    return (nx - (lx + rx) / 2) / eye if eye >= 2 else 9.0


def pitch_of(row) -> float:
    """Head tilt from YuNet's landmarks: nose below the eyes, in eye-distances (~0.5 level)."""
    ry, ly, ny = float(row[5]), float(row[7]), float(row[9])
    eye = abs(float(row[6]) - float(row[4]))
    return (ny - (ly + ry) / 2) / eye if eye >= 2 else 9.0


def facing(row) -> bool:
    """Is a YuNet face turned toward the screen? The nose sits between the eyes when
    you face the camera and swings out when you turn away."""
    return abs(yaw_of(row)) < 0.35 and 0.15 < pitch_of(row) < 1.3


# --- your face, remembered (D37) ---------------------------------------------

def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI: bytes only this Windows user, on this machine, can decrypt."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), Blob()
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(src), "Jimmy: owner face", None, None, None, 1, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(out))
    if not ok:
        raise OSError(f"DPAPI failed ({ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


class OwnerFace:
    """Your face template: k SFace vectors, DPAPI-encrypted on disk. Only ever
    written by a finished guided capture you asked for."""
    MAGIC = b"JIMMY-OWNER-1"

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.DATA_DIR / "owner_face.bin")
        self.vectors: np.ndarray | None = None
        self.load()

    def __getstate__(self):
        raise TypeError("the owner template is never serialised except by DPAPI, to its own file")

    def __reduce__(self):
        raise TypeError("the owner template is never serialised except by DPAPI, to its own file")

    @property
    def known(self) -> bool:
        return self.vectors is not None and len(self.vectors) > 0

    def load(self) -> None:
        self.vectors = None
        if not self.path.exists():
            return
        try:
            raw = _dpapi(self.path.read_bytes(), protect=False)
        except OSError as exc:
            print(f"[presence] can't read the remembered face: {exc}")
            return
        if raw.startswith(self.MAGIC):
            self.vectors = np.frombuffer(raw[len(self.MAGIC):], dtype=np.float32).reshape(-1, 128).copy()

    def save(self, vectors: list[np.ndarray]) -> None:
        v = np.asarray([x.ravel() for x in vectors], dtype=np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(_dpapi(self.MAGIC + v.tobytes(), protect=True))
        self.vectors = v

    def forget(self) -> None:
        self.path.unlink(missing_ok=True)
        self.vectors = None

    def match(self, feat: np.ndarray) -> float:
        """Best cosine similarity to your template (0..1); 0 if nothing is remembered."""
        if not self.known:
            return 0.0
        f = feat.ravel().astype(np.float32)
        return float((self.vectors @ (f / (np.linalg.norm(f) + 1e-9))).max())


# --- the guided capture --------------------------------------------------------

STEPS = (("Look straight at the camera.", 6), ("Turn your head a little to one side.", 4),
         ("Now a little to the other side.", 4))


def check(faces, gray: np.ndarray, step: int, side: float) -> tuple[str, bool]:
    """What to tell you about this frame, and whether it's good enough to keep."""
    H, W = gray.shape
    if not len(faces):
        return "I can't see your face. Sit in front of the camera.", False
    if len(faces) > 1:
        return "Just you, please: someone else is in view.", False
    x, y, w, h = (float(v) for v in faces[0][:4])
    if w < 0.18 * W:
        return "Come a little closer.", False
    if w > 0.6 * W:
        return "Move back a little.", False
    cx, cy = (x + w / 2) / W, (y + h / 2) / H
    if not (0.25 < cx < 0.75 and 0.2 < cy < 0.8):
        return "Move into the middle of the picture.", False
    crop = gray[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)]
    if crop.size == 0:
        return "Move into the middle of the picture.", False
    if crop.mean() < config.ENROL_MIN_LIGHT:
        return "It's a bit dark. Turn on a light, or face a window.", False
    if crop.mean() > config.ENROL_MAX_LIGHT:
        return "Too much light on your face. Turn away from it a little.", False
    if cv2.Laplacian(crop, cv2.CV_64F).var() < config.ENROL_MIN_SHARP:
        return "Hold still for a moment.", False
    yaw = yaw_of(faces[0])
    if step == 0 and abs(yaw) > 0.12:
        return STEPS[0][0], False
    if step == 1 and not 0.15 < abs(yaw) < 0.55:
        return STEPS[1][0], False
    if step == 2 and not (0.15 < abs(yaw) < 0.55 and np.sign(yaw) == -side):
        return STEPS[2][0], False
    return "Hold it there.", True


class Enrolment:
    """Samples so far, and which step we're on. Lives only while capturing."""

    def __init__(self, started: float):
        self.started, self.step, self.side, self.taken = started, 0, 0.0, 0.0
        self.samples: list[np.ndarray] = []
        self.per_step = [0, 0, 0]

    def take(self, t: float, feat: np.ndarray, yaw: float) -> None:
        if t - self.taken < 0.25:
            return
        self.taken = t
        if self.step == 1 and not self.per_step[1]:
            self.side = float(np.sign(yaw))
        self.samples.append(feat.ravel().copy())
        self.per_step[self.step] += 1
        if self.per_step[self.step] >= STEPS[self.step][1]:
            self.step += 1

    @property
    def done(self) -> bool:
        return self.step >= len(STEPS)

    @property
    def progress(self) -> float:
        return sum(self.per_step) / sum(n for _, n in STEPS)

    def consistent(self) -> bool:
        """The looking-straight samples must agree with each other: a blurred or
        half-lit capture shows up as a spread, and a bad template locks you out."""
        v = np.asarray(self.samples[:STEPS[0][1]], dtype=np.float32)
        v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
        sims = v @ v.T
        return float(sims[np.triu_indices(len(v), 1)].min()) >= config.ENROL_MIN_AGREE


# --- presence --------------------------------------------------------------------

class Tracker:
    """Per-frame observations -> a steady state, with hysteresis (D39).

    `you`: your face, or the place it was followed to, is in the picture this frame.
    Where you look doesn't matter: only leaving the picture brings the curtain."""

    def __init__(self):
        self.state = "present"
        self._cond, self._since = "you", 0.0

    def update(self, t: float, you: bool, others: int = 0, dark: bool = False, stranger: bool = False) -> str:
        cond = ("dark" if dark else ("many" if others else "you") if you
                else "stranger" if stranger else "none")
        if cond != self._cond:
            self._cond, self._since = cond, t
        held = t - self._since
        if cond == "dark" and held >= 10:
            self.state = "off"
        elif cond == "none" and held >= config.AWAY_S:
            self.state = "away"
        elif cond == "stranger" and held >= config.STRANGER_S:
            self.state = "stranger"
        elif cond == "many" and held >= config.WATCHED_S:
            self.state = "watched"
        elif cond == "you" and held >= config.RETURN_S:
            self.state = "present"
        return self.state


def _iou(a, b) -> float:
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter + 1e-9)


def _near(face, box) -> bool:
    """The same face as the followed box: overlapping, or its centre close (a quick move)."""
    x, y, w, h = (float(v) for v in face[:4])
    bx, by, bw, bh = box
    return _iou(face[:4], box) >= 0.3 or np.hypot(x + w / 2 - bx - bw / 2, y + h / 2 - by - bh / 2) <= 0.6 * bw


_Q = 0.25          # template matching runs on a quarter-size picture (160x120)


def _region(box, W: float, H: float) -> tuple[int, int, int, int]:
    """Head and shoulders around a face box, clipped to the picture, in quarter-size pixels."""
    x, y, w, h = box
    return (max(0, int((x - 0.6 * w) * _Q)), max(0, int((y - 0.4 * h) * _Q)),
            min(int(W * _Q), int((x + 1.6 * w) * _Q) + 1), min(int(H * _Q), int((y + 2.0 * h) * _Q) + 1))


class Follow:
    """Where you are in the picture (D39). Marked from a face the detector found;
    when it loses the face (head turned, looking down, a hand in the way), the
    head-and-shoulders patch around it is found again nearby by template matching.
    The patch is refreshed only from a real detection, so it can't learn the empty
    chair, and with no face at all for BLIND_MAX_S it is no longer trusted.
    RAM only; it dies with the track."""

    def __init__(self, row, q: np.ndarray, t: float):
        self.owner: bool | None = None      # with a remembered face: you / not you / not judged yet
        self.tries, self.checked, self.misses = 0, -1e9, 0
        self.mouth: np.ndarray | None = None
        self.mouth_t = -1e9
        self.saw(row, q, t)

    def __getstate__(self):
        raise TypeError("a face track is ephemeral by design and must never be serialised")

    def __reduce__(self):
        raise TypeError("a face track is ephemeral by design and must never be serialised")

    def saw(self, row, q: np.ndarray, t: float) -> None:
        self.box = [float(v) for v in row[:4]]
        self.seen = self.alive = t
        x0, y0, x1, y1 = self.at = _region(self.box, q.shape[1] / _Q, q.shape[0] / _Q)
        self.patch = q[y0:y1, x0:x1].copy()

    def find(self, q: np.ndarray, t: float) -> float:
        """Your patch near where it was: the match, 0..1. Found -> the box moves with it."""
        if t - self.seen > config.BLIND_MAX_S:
            return 0.0
        x0, y0, x1, y1 = self.at
        ph, pw = self.patch.shape
        if pw < 4 or ph < 4 or float(self.patch.std()) < 2:
            return 0.0
        m = max(2, int(0.6 * self.box[2] * _Q))
        H, W = q.shape
        ax0, ay0 = max(0, x0 - m), max(0, y0 - m)
        area = q[ay0:min(H, y1 + m), ax0:min(W, x1 + m)]
        if area.shape[0] < ph or area.shape[1] < pw:
            return 0.0
        _, score, _, (lx, ly) = cv2.minMaxLoc(cv2.matchTemplate(area, self.patch, cv2.TM_CCOEFF_NORMED))
        score = float(score) if np.isfinite(score) else 0.0
        if score >= config.FOLLOW_MIN:
            dx, dy = ax0 + lx - x0, ay0 + ly - y0
            self.at = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self.box[0] += dx / _Q
            self.box[1] += dy / _Q
            self.alive = t
        return score


# --- talking to Jimmy without its name (D39) ----------------------------------------

def irises(gray: np.ndarray, row) -> tuple[float, float] | None:
    """Where the irises sit relative to YuNet's eye points, in eye-distances: the
    darkest fifth of a small box round each eye, weighted by darkness, both eyes
    averaged. ponytail: a plain webcam and no gaze model; good for "at the screen
    or not", not for which word you're reading."""
    rx, ry, lx, ly = (float(v) for v in row[4:8])
    d = abs(lx - rx)
    if d < config.GAZE_MIN_EYES:
        return None
    H, W = gray.shape
    out = []
    for ex, ey in ((rx, ry), (lx, ly)):
        x0, x1 = int(ex - 0.22 * d), int(ex + 0.22 * d) + 1
        y0, y1 = int(ey - 0.12 * d), int(ey + 0.12 * d) + 1
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            return None
        c = cv2.GaussianBlur(gray[y0:y1, x0:x1], (3, 3), 0).astype(np.float32)
        wgt = np.clip(np.percentile(c, 20) + 1 - c, 0, None)
        s = float(wgt.sum())
        if s <= 0:
            return None
        ys, xs = np.mgrid[y0:y1, x0:x1]
        out.append((float((wgt * xs).sum()) / s - ex, float((wgt * ys).sum()) / s - ey))
    return (out[0][0] + out[1][0]) / (2 * d), (out[0][1] + out[1][1]) / (2 * d)


def mouth_of(gray: np.ndarray, row) -> np.ndarray | None:
    """The mouth, from YuNet's two corners, at a fixed small size and contrast, so
    two frames compare: lips moving change it, a still face barely does."""
    ax, ay, bx, by = (float(v) for v in row[10:14])
    w = abs(bx - ax)
    if w < 10:
        return None
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    x0, x1, y0, y1 = int(cx - 0.75 * w), int(cx + 0.75 * w) + 1, int(cy - 0.45 * w), int(cy + 0.6 * w) + 1
    H, W = gray.shape
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        return None
    p = cv2.resize(gray[y0:y1, x0:x1], (24, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
    return (p - p.mean()) / (p.std() + 8)


class Gaze:
    """Where you normally look, learnt while you work (D39): head turn, head tilt and
    iris position while you're at the screen. Eye contact = all four inside that
    zone; looking down at a phone or off to the side is outside it. RAM only, per
    run; until it has learnt enough, facing the screen counts."""

    def __init__(self, n: int = 600):
        self.samples: deque = deque(maxlen=n)
        self._zone: tuple[np.ndarray, np.ndarray] | None = None

    def __getstate__(self):
        raise TypeError("gaze calibration is ephemeral by design and must never be serialised")

    def contact(self, row, eyes: tuple[float, float] | None) -> bool:
        if not facing(row) or eyes is None:
            return False
        v = np.array([yaw_of(row), pitch_of(row), eyes[0], eyes[1]], dtype=np.float32)
        self.samples.append(v)
        if len(self.samples) < config.GAZE_LEARN_N:
            return True
        if self._zone is None or len(self.samples) % 20 == 0:
            a = np.asarray(self.samples)
            med = np.median(a, axis=0)
            spread = np.maximum(np.median(np.abs(a - med), axis=0) * 1.4826, config.GAZE_MIN_SPREAD)
            self._zone = (med, spread)
        med, spread = self._zone
        return bool(np.all(np.abs(v - med) <= config.GAZE_ZONE * spread))


class Presence:
    def __init__(self, on_change: Callable[[dict], None], camera: int | None = None,
                 on_enrol: Callable[[dict], None] = lambda e: None, owner: OwnerFace | None = None):
        self.on_change, self.on_enrol = on_change, on_enrol
        self.camera = config.PRESENCE_CAMERA if camera is None else camera
        self.owner = owner or OwnerFace()
        self.info = {"state": "starting", "faces": 0, "facing": False, "contact": False, "why": ""}
        self.track: Follow | None = None
        self.last_match = 1.0
        self.gaze = Gaze()
        # D39: (epoch ms, eye contact, lips moving, facing) per frame of *you*, last two
        # minutes, so a spoken line can be checked against what the camera saw. Values
        # only; None where it couldn't tell.
        self.history: deque = deque(maxlen=480)
        self._stop = threading.Event()
        self._enrol: Enrolment | None = None
        self._want_enrol = False

    # Like FaceStage: nothing here is ever serialised.
    def __getstate__(self):
        raise TypeError("Presence is ephemeral by design and must never be serialised")

    def __reduce__(self):
        raise TypeError("Presence is ephemeral by design and must never be serialised")

    @property
    def enrolling(self) -> bool:
        return self._enrol is not None or self._want_enrol

    def start(self) -> "Presence":
        threading.Thread(target=self._run, daemon=True, name="presence").start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def enrol(self) -> str:
        """Start the guided capture (on the presence thread, which owns the camera)."""
        if self.info.get("state") == "off" and self.info.get("why"):
            return f"I can't see the camera: {self.info['why']}."
        self._want_enrol = True
        return "Let's do it. Look at the screen."

    def cancel_enrol(self) -> None:
        if self.enrolling:
            self._want_enrol, self._enrol = False, None
            self.on_enrol({"done": True, "failed": True, "say": "Cancelled. Nothing was kept."})

    def forget(self) -> str:
        known = self.owner.known
        self.owner.forget()
        self.track = None
        return "Forgotten. Your face template is deleted." if known else "I didn't have your face."

    # --- what the camera saw while something was said (D39) -----------------------
    def _during(self, t0: int, t1: int) -> list:
        return [h for h in list(self.history) if t0 <= h[0] <= t1]

    def spoke(self, t0: int, t1: int) -> bool | None:
        """Did your lips move while this was said (epoch ms)? None: couldn't see them."""
        m = [h[2] for h in self._during(t0 - 300, t1 + 300) if h[2] is not None]
        return None if len(m) < 2 else sum(m) / len(m) >= config.MOUTH_SHARE

    def facing_during(self, t0: int, t1: int) -> bool | None:
        """Were you turned to the screen while this was said? None: you weren't in view."""
        f = [h[3] for h in self._during(t0 - 300, t1 + 300) if h[3] is not None]
        return None if not f else sum(f) / len(f) >= 0.5

    def eye_contact(self, t0: int, t1: int) -> bool:
        """Were you looking at the screen as you started to speak?"""
        c = [h[1] for h in self._during(t0 - 700, min(t1, t0 + 1500)) if h[1] is not None]
        return len(c) >= 2 and sum(c) / len(c) >= 0.5

    def _set(self, **kw) -> None:
        new = {**self.info, **kw}
        if new != self.info:
            self.info = new
            self.on_change(dict(new))

    def _enrol_tick(self, t: float, small: np.ndarray, gray: np.ndarray, faces, rec) -> None:
        e = self._enrol
        if t - e.started > config.ENROL_TIMEOUT_S:
            self._enrol = None
            self.on_enrol({"done": True, "failed": True, "say": "That took too long. Say \"remember my face\" to try again."})
            return
        say, ok = check(faces, gray, e.step, e.side)
        if ok:
            try:
                feat = rec.feature(rec.alignCrop(small, faces[0]))
                e.take(t, feat, yaw_of(faces[0]))
            except cv2.error:
                ok = False
        if e.done:
            self._enrol = None
            if not e.consistent():
                self.on_enrol({"done": True, "failed": True,
                               "say": "That didn't come out clearly. Let's try again with steadier light."})
                return
            self.owner.save(e.samples)          # the only write of a face vector, anywhere (D37)
            self.track = None                   # judge the face in front again, with the template
            self.on_enrol({"done": True, "failed": False, "progress": 1.0,
                           "say": "Got it. I'll know you now. Say \"forget my face\" any time."})
            return
        H, W = gray.shape
        mirror = cv2.flip(cv2.resize(small, (320, int(320 * H / W))), 1)     # a mirror, like a selfie
        jpg = cv2.imencode(".jpg", mirror, [cv2.IMWRITE_JPEG_QUALITY, 60])[1].tobytes()
        box = None
        if len(faces) == 1:
            x, y, w, h = (float(v) for v in faces[0][:4])
            box = [1 - (x + w) / W, y / H, w / W, h / H]                   # mirrored too
        self.on_enrol({"done": False, "step": e.step, "steps": len(STEPS), "say": say, "ok": ok,
                       "progress": e.progress, "box": box,
                       "preview": "data:image/jpeg;base64," + base64.b64encode(jpg).decode()})

    def _identify(self, t: float, small: np.ndarray, strong: list, on, rec, q: np.ndarray):
        """With your face remembered: who the followed face is. Judged when a track
        starts and re-checked every REVERIFY_S, never every frame (D39): one bad,
        dim frame no longer drops the curtain on you. Only the score survives a
        comparison; the vector is gone with the line that made it (D37)."""
        def score(f) -> float:
            try:
                return self.owner.match(rec.feature(rec.alignCrop(small, f)))
            except cv2.error:
                return 0.0
        tr = self.track
        if tr is not None and tr.owner is True:
            if on is not None and facing(on) and t - tr.checked >= config.REVERIFY_S:
                tr.checked = t
                tr.misses = tr.misses + 1 if score(on) < config.OWNER_KEEP else 0
                if tr.misses >= 2:
                    tr.owner, tr.tries = False, config.ID_TRIES        # not you after all
            return on
        every = config.ID_EVERY_S if tr is None or tr.owner is None else 2.0
        if not strong or (tr is not None and t - tr.checked < every):
            return on
        for f in sorted(strong, key=lambda f: -float(f[2]))[:3]:
            if score(f) >= config.OWNER_MATCH:
                if tr is None or not _near(f, tr.box):
                    self.track = tr = Follow(f, q, t)
                tr.owner, tr.checked = True, t
                return f
        if tr is None:
            on = max(strong, key=lambda f: float(f[2]))
            self.track = tr = Follow(on, q, t)
        tr.checked, tr.tries = t, tr.tries + 1
        if tr.owner is None and tr.tries >= config.ID_TRIES:
            tr.owner = False                    # someone at the screen, and it isn't you
        return on

    def observe(self, t: float, small: np.ndarray, gray: np.ndarray, faces: list, rec, tracker: Tracker) -> str:
        """One frame -> the state (D39). `faces`: YuNet rows scoring >= PRESENCE_KEEP_SCORE."""
        dark = float(gray.mean()) < config.DARK_FRAME
        q = cv2.resize(gray, (gray.shape[1] // 4, gray.shape[0] // 4), interpolation=cv2.INTER_AREA)
        strong = [f for f in faces if float(f[14]) >= config.FACE_SCORE_THRESHOLD and facing(f)]
        tr, on = self.track, None
        if tr is not None:
            close = [f for f in faces if _near(f, tr.box)]
            if close:
                on = max(close, key=lambda f: _iou(f[:4], tr.box))
                tr.saw(on, q, t)
            else:
                self.last_match = tr.find(q, t)     # kept for the log: FOLLOW_MIN is tuned from it
                if self.last_match < config.FOLLOW_MIN and t - tr.alive >= config.AWAY_S:
                    self.track = tr = None          # out of the picture this long: gone
        known = self.owner.known
        if known and rec is not None:
            on = self._identify(t, small, strong, on, rec, q)
            tr = self.track
        elif tr is None and strong:
            on = max(strong, key=lambda f: float(f[2]))
            self.track = tr = Follow(on, q, t)
        alive = tr is not None and tr.alive == t
        mine = alive and (tr.owner is True or not known)
        others = sum(1 for f in strong if not _near(f, tr.box)) if alive else 0
        contact = moving = looking = None
        if mine and on is not None:
            looking = facing(on)
            contact = self.gaze.contact(on, irises(gray, on))
            m = mouth_of(gray, on)
            if m is not None and tr.mouth is not None and t - tr.mouth_t <= 0.8:
                moving = float(np.abs(m - tr.mouth).mean()) >= config.MOUTH_MOVING
            tr.mouth, tr.mouth_t = m, t
        elif mine:
            looking = False                     # followed, face not in view: turned away
        self.history.append((int(time.time() * 1000), contact, moving, looking))
        return tracker.update(t, mine, others, dark, stranger=alive and known and tr.owner is False)

    def _run(self) -> None:
        from .audio import other_app_using
        det = cv2.FaceDetectorYN.create(str(config.MODELS_DIR / YUNET), "", (640, 480),
                                        config.PRESENCE_KEEP_SCORE, config.FACE_NMS_THRESHOLD, 10)
        rec = None                                   # SFace: loaded only for your remembered face
        tracker, cap, busy, check_at = Tracker(), None, False, 0.0
        probe, looked = None, -1e9                   # D39: away, a cheap motion check between looks
        try:
            while not self._stop.is_set():
                t0 = time.monotonic()
                if t0 >= check_at:          # a call wants the camera: let go of it
                    check_at, busy = t0 + 5, other_app_using("webcam")
                    if busy and cap is not None:
                        cap.release()
                        cap = None
                if busy:
                    self.track = None
                    self._set(state="off", faces=0, facing=False, contact=False, why="another app is using the camera")
                    if self.enrolling:
                        self.cancel_enrol()
                    self._stop.wait(1)
                    continue
                if cap is None:
                    cap = cv2.VideoCapture(self.camera, cv2.CAP_MSMF)
                    if not cap.isOpened():
                        cap = None
                        self._set(state="off", faces=0, facing=False, contact=False, why="no camera")
                        self._stop.wait(10)
                        continue
                    # D38: 640x480 at a few fps, not the driver's default 30: we read 4.
                    # The driver may refuse; whatever it gives is still used as before.
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, config.PRESENCE_CAMERA_FPS)
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    cap = None
                    self.track = None
                    self._set(state="off", why="camera stopped")
                    self._stop.wait(2)
                    continue
                H, W = frame.shape[:2]
                small = cv2.resize(frame, (640, int(640 * H / W)), interpolation=cv2.INTER_AREA) if W > 640 else frame
                del frame                              # the full frame dies here, every tick
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                resting = tracker.state == "away" and self.track is None and not self.enrolling
                if resting:
                    # D39: you left and the curtain is down. Look properly every
                    # AWAY_CHECK_S, or at once when the picture moves (you sitting down).
                    tiny = cv2.resize(gray, (40, 30), interpolation=cv2.INTER_AREA).astype(np.int16)
                    moved = probe is not None and float(np.abs(tiny - probe).mean()) >= config.AWAY_MOTION
                    probe = tiny
                    if not moved and t0 - looked < config.AWAY_CHECK_S:
                        del small, gray
                        self._stop.wait(max(0.0, 1.0 - (time.monotonic() - t0)))
                        continue
                else:
                    probe = None
                looked = t0
                det.setInputSize((small.shape[1], small.shape[0]))
                try:
                    _, faces = det.detect(small)
                except cv2.error:
                    faces = None
                faces = [f for f in (faces if faces is not None else [])
                         if f[2] >= config.PRESENCE_MIN_FACE * small.shape[1]]
                if self._want_enrol:
                    self._want_enrol, self._enrol = False, Enrolment(t0)
                if (self._enrol is not None or self.owner.known) and rec is None:
                    rec = cv2.FaceRecognizerSF.create(str(config.MODELS_DIR / SFACE), "")
                if self._enrol is not None:
                    self._enrol_tick(t0, small, gray, [f for f in faces if f[14] >= config.FACE_SCORE_THRESHOLD],
                                     rec)
                    del small, gray
                    self._stop.wait(max(0.0, 1 / config.ENROL_FPS - (time.monotonic() - t0)))
                    continue
                state = self.observe(t0, small, gray, faces, rec, tracker)
                del small, gray
                recent = list(self.history)[-3:]
                self._set(state=state, faces=len(faces), facing=bool(recent and recent[-1][3]),
                          contact=sum(bool(h[1]) for h in recent) >= 2, owner=self.owner.known,
                          why="lens covered or dark" if state == "off" else
                          f"out of the picture; last match {self.last_match:.2f}, FOLLOW_MIN {config.FOLLOW_MIN}"
                          if state == "away" else "")
                wait = 1.0 if state == "away" and self.track is None else 1 / config.PRESENCE_FPS
                self._stop.wait(max(0.0, wait - (time.monotonic() - t0)))
        except Exception as exc:                      # presence is optional; capture goes on
            print(f"[presence] stopped: {type(exc).__name__}: {exc}")
            self._set(state="off", why="error")
        finally:
            if cap is not None:
                cap.release()
