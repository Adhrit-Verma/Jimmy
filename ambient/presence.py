"""Presence from your own webcam, for the privacy curtain (D34, D37).

It counts faces and reads which way the nearest one is turned. Two modes:

- **Nothing remembered** (the default): it recognises no one. "present" is any
  one face at the screen.
- **"Jimmy, remember my face"** (D37, the one exception to non-negotiable 2,
  made by the human on 2026-10-02): a guided capture turns *your* face into a
  template: a few SFace vectors, no image, stored encrypted with Windows DPAPI
  so only your Windows account can read it. Then "present" means you, and
  someone else alone at the screen is "stranger". Every other face's vector
  exists for one comparison inside one loop iteration and is dropped: never
  stored, never logged, never compared with anything but your template.
  "Jimmy, forget my face" deletes the template.

States: present / away / watched (you and someone else) / stranger / off.
Nothing here is ever serialised; no frame outlives its tick.
"""
from __future__ import annotations

import base64
import threading
import time
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


def facing(row) -> bool:
    """Is a YuNet face turned toward the screen? The nose sits between the eyes when
    you face the camera and swings out when you turn away.
    ponytail: head pose, not gaze; a plain webcam reads where eyes point poorly."""
    ry, ly, ny = float(row[5]), float(row[7]), float(row[9])
    eye = abs(float(row[6]) - float(row[4]))
    if eye < 2:
        return False
    pitch = (ny - (ly + ry) / 2) / eye
    return abs(yaw_of(row)) < 0.35 and 0.15 < pitch < 1.3


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
    """Per-frame observations -> a steady state, with hysteresis so a blink, a
    turned head or one bad frame doesn't flap the curtain."""

    def __init__(self):
        self.state = "present"
        self._cond, self._since = "one", 0.0
        self._turned_since: float | None = None

    def update(self, t: float, n: int, is_facing: bool, dark: bool,
               owner: bool | None = None, strangers: int = 0) -> tuple[str, bool]:
        """`owner`: None = no face remembered (any face counts); True/False = your
        remembered face is / isn't among the faces turned to the screen."""
        if dark:
            cond = "dark"
        elif n == 0:
            cond = "none"
        elif owner is False and strangers:
            cond = "stranger"                    # someone at the screen, and it isn't you
        elif n > 1:
            cond = "many"
        elif owner or (owner is None and is_facing):
            cond = "one"
        else:
            cond = "turned"
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
        elif cond == "one" and held >= config.RETURN_S:
            self.state = "present"
        elif cond == "turned" and self.state == "watched" and held >= config.RETURN_S:
            self.state = "present"          # the other person left; you're looking down
        self._turned_since = (self._turned_since or t) if cond == "turned" else None
        looking_away = bool(config.LOOK_AWAY_S and self._turned_since
                            and t - self._turned_since >= config.LOOK_AWAY_S)
        return self.state, looking_away


def _iou(a, b) -> float:
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter + 1e-9)


def _same_faces(verdict: dict, boxes: list, t: float) -> bool:
    """Is the last identity verdict still about these faces? Same count, each box
    overlapping its old place by half or more, and no older than PRESENCE_REID_S."""
    old = verdict["boxes"]
    if t - verdict["at"] > config.PRESENCE_REID_S or len(old) != len(boxes) or not boxes:
        return False
    return all(max(_iou(b, o) for o in old) >= 0.5 for b in boxes)


class Presence:
    def __init__(self, on_change: Callable[[dict], None], camera: int | None = None,
                 on_enrol: Callable[[dict], None] = lambda e: None, owner: OwnerFace | None = None):
        self.on_change, self.on_enrol = on_change, on_enrol
        self.camera = config.PRESENCE_CAMERA if camera is None else camera
        self.owner = owner or OwnerFace()
        self.info = {"state": "starting", "faces": 0, "facing": False, "looking_away": False, "why": ""}
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
        return "Forgotten. Your face template is deleted." if known else "I didn't have your face."

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

    def _run(self) -> None:
        from .audio import other_app_using
        det = cv2.FaceDetectorYN.create(str(config.MODELS_DIR / YUNET), "", (640, 480),
                                        config.FACE_SCORE_THRESHOLD, config.FACE_NMS_THRESHOLD, 10)
        rec = None                                   # SFace: loaded only for your remembered face
        tracker, cap, busy, check_at = Tracker(), None, False, 0.0
        verdict: dict = {"at": -1e9, "boxes": [], "owner": None, "strangers": 0}   # D38
        try:
            while not self._stop.is_set():
                t0 = time.monotonic()
                if t0 >= check_at:          # a call wants the camera: let go of it
                    check_at, busy = t0 + 5, other_app_using("webcam")
                    if busy and cap is not None:
                        cap.release()
                        cap = None
                if busy:
                    self._set(state="off", faces=0, facing=False, why="another app is using the camera")
                    if self.enrolling:
                        self.cancel_enrol()
                    self._stop.wait(1)
                    continue
                if cap is None:
                    cap = cv2.VideoCapture(self.camera, cv2.CAP_MSMF)
                    if not cap.isOpened():
                        cap = None
                        self._set(state="off", faces=0, facing=False, why="no camera")
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
                    self._set(state="off", why="camera stopped")
                    self._stop.wait(2)
                    continue
                H, W = frame.shape[:2]
                small = cv2.resize(frame, (640, int(640 * H / W)), interpolation=cv2.INTER_AREA) if W > 640 else frame
                del frame                              # the full frame dies here, every tick
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
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
                    self._enrol_tick(t0, small, gray, faces, rec)
                    del small, gray
                    self._stop.wait(max(0.0, 1 / config.ENROL_FPS - (time.monotonic() - t0)))
                    continue
                dark = float(gray.mean()) < config.DARK_FRAME
                near = max(faces, key=lambda f: f[2]) if faces else None
                is_facing = bool(near is not None and facing(near))
                owner_here, strangers = None, 0
                facing_boxes = [f[:4] for f in faces if facing(f)]
                if self.owner.known and _same_faces(verdict, facing_boxes, t0):
                    # D38: the same faces in the same places as half a second ago: the
                    # identity verdict stands. Only the yes/no is kept, never a vector.
                    owner_here, strangers = verdict["owner"], verdict["strangers"]
                elif self.owner.known:
                    owner_here = False
                    for f in faces:
                        if not facing(f):
                            continue                     # identity only from a face turned to the screen
                        try:
                            score = self.owner.match(rec.feature(rec.alignCrop(small, f)))
                        except cv2.error:
                            continue
                        # Only the score survives: the vector is gone with this line (D37).
                        if score >= config.OWNER_MATCH:
                            owner_here = True
                        else:
                            strangers += 1
                    verdict.update(at=t0, boxes=facing_boxes, owner=owner_here, strangers=strangers)
                del small, gray
                state, away = tracker.update(t0, len(faces), is_facing, dark, owner_here, strangers)
                self._set(state=state, faces=len(faces), facing=is_facing, looking_away=away,
                          owner=self.owner.known, why="lens covered or dark" if state == "off" else "")
                self._stop.wait(max(0.0, 1 / config.PRESENCE_FPS - (time.monotonic() - t0)))
        except Exception as exc:                      # presence is optional; capture goes on
            print(f"[presence] stopped: {type(exc).__name__}: {exc}")
            self._set(state="off", why="error")
        finally:
            if cap is not None:
                cap.release()
