"""Presence from your own webcam, for the privacy curtain (D34).

It counts faces and reads which way the nearest one is turned. It never
recognises anyone: no face vector is computed from the webcam (non-negotiable 2:
the face stage never enrols or names), no frame outlives its tick, nothing is
written or logged. Only a state leaves this object:

    present  one face, at the screen          -> normal
    away     no face for AWAY_S               -> curtain
    watched  more than one face for WATCHED_S -> shoulder-surf: hide or curtain
    off      no camera, lens covered, or another app is using the camera

ponytail: "present" is any one face, not *your* face. Telling you from someone
else would need an enrolled template, which the spec rules out. The curtain is a
screen against glances, not a lock.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import cv2

from . import config
from .redact import YUNET


def facing(row) -> bool:
    """Is a YuNet face turned toward the screen? From its landmarks: the nose sits
    between the eyes when you face the camera and swings out when you turn away.
    ponytail: head pose, not gaze. A plain webcam can't tell where eyes point
    without a gaze model; head direction is what this hardware can read well."""
    rx, ry, lx, ly, nx, ny = (float(v) for v in row[4:10])
    eye = abs(lx - rx)
    if eye < 2:
        return False
    yaw = (nx - (lx + rx) / 2) / eye
    pitch = (ny - (ly + ry) / 2) / eye
    return abs(yaw) < 0.35 and 0.15 < pitch < 1.3


class Tracker:
    """Per-frame counts -> a steady state, with hysteresis so a blink, a turned
    head or a face lost for one frame doesn't flap the curtain."""

    def __init__(self):
        self.state = "present"
        self._cond, self._since = "one", 0.0
        self._turned_since: float | None = None

    def update(self, t: float, n: int, is_facing: bool, dark: bool) -> tuple[str, bool]:
        cond = "dark" if dark else "none" if n == 0 else "many" if n > 1 else "one" if is_facing else "turned"
        if cond != self._cond:
            self._cond, self._since = cond, t
        held = t - self._since
        if cond == "dark" and held >= 10:
            self.state = "off"
        elif cond == "none" and held >= config.AWAY_S:
            self.state = "away"
        elif cond == "many" and held >= config.WATCHED_S:
            self.state = "watched"
        elif cond == "one" and held >= config.RETURN_S:
            self.state = "present"
        elif cond == "turned" and self.state == "watched" and held >= config.RETURN_S:
            self.state = "present"          # the other person left; you're looking down
        # Looking away for long (optional): reading paper is normal, so off by default.
        self._turned_since = (self._turned_since or t) if cond == "turned" else None
        looking_away = bool(config.LOOK_AWAY_S and self._turned_since
                            and t - self._turned_since >= config.LOOK_AWAY_S)
        return self.state, looking_away


class Presence:
    def __init__(self, on_change: Callable[[dict], None], camera: int | None = None):
        self.on_change = on_change
        self.camera = config.PRESENCE_CAMERA if camera is None else camera
        self.info = {"state": "starting", "faces": 0, "facing": False, "looking_away": False, "why": ""}
        self._stop = threading.Event()

    # Like FaceStage: nothing here is ever serialised.
    def __getstate__(self):
        raise TypeError("Presence is ephemeral by design and must never be serialised")

    def __reduce__(self):
        raise TypeError("Presence is ephemeral by design and must never be serialised")

    def start(self) -> "Presence":
        threading.Thread(target=self._run, daemon=True, name="presence").start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _set(self, **kw) -> None:
        new = {**self.info, **kw}
        if new != self.info:
            self.info = new
            self.on_change(dict(new))

    def _run(self) -> None:
        from .audio import other_app_using
        det = cv2.FaceDetectorYN.create(str(config.MODELS_DIR / YUNET), "", (320, 240),
                                        config.FACE_SCORE_THRESHOLD, config.FACE_NMS_THRESHOLD, 10)
        tracker, cap, busy, check_at = Tracker(), None, False, 0.0
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
                    self._stop.wait(1)
                    continue
                if cap is None:
                    cap = cv2.VideoCapture(self.camera, cv2.CAP_MSMF)
                    if not cap.isOpened():
                        cap = None
                        self._set(state="off", faces=0, facing=False, why="no camera")
                        self._stop.wait(10)
                        continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    cap.release()
                    cap = None
                    self._set(state="off", why="camera stopped")
                    self._stop.wait(2)
                    continue
                small = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_AREA)
                del frame                              # the frame dies here, every tick
                dark = float(small.mean()) < config.DARK_FRAME
                det.setInputSize((320, 240))
                try:
                    _, faces = det.detect(small)
                except cv2.error:
                    faces = None
                del small
                faces = [f for f in (faces if faces is not None else []) if f[2] >= config.PRESENCE_MIN_FACE * 320]
                near = max(faces, key=lambda f: f[2]) if faces else None
                is_facing = bool(near is not None and facing(near))
                state, away = tracker.update(t0, len(faces), is_facing, dark)
                self._set(state=state, faces=len(faces), facing=is_facing, looking_away=away,
                          why="lens covered or dark" if state == "off" else "")
                self._stop.wait(max(0.0, 1 / config.PRESENCE_FPS - (time.monotonic() - t0)))
        except Exception as exc:                      # presence is optional; capture goes on
            print(f"[presence] stopped: {type(exc).__name__}: {exc}")
            self._set(state="off", why="error")
        finally:
            if cap is not None:
                cap.release()
