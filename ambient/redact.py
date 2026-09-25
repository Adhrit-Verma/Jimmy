"""Everything that decides what must never reach disk.

Two jobs, one file, because they answer the same question:

1. Exclusions -- whole surfaces we refuse to capture at all (password managers,
   banking, private windows). Non-negotiable 4: this ships before first run.
2. The face stage -- ephemeral differentiation. Faces are blurred *before* the
   write, so a stored artifact never contains one. Vectors live in RAM keyed by
   the capture window and die with it. Non-negotiable 2: there is no persistence
   path here, not a setting that defaults to off.
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from . import config

# --- exclusions ----------------------------------------------------------

EXCLUDED_EXES = {
    "1password.exe", "bitwarden.exe", "keepass.exe", "keepass2.exe", "keepassxc.exe",
    "lastpass.exe", "dashlane.exe", "keeper.exe", "keeperpasswordmanager.exe",
    "nordpass.exe", "protonpass.exe", "enpass.exe", "roboform.exe", "padloc.exe",
    "credentialuibroker.exe", "lsaiso.exe", "consent.exe", "logonui.exe",
}

# Matched case-insensitively against the window title.
EXCLUDED_TITLE_PATTERNS = [
    r"\bincognito\b", r"\binprivate\b", r"private browsing", r"\bprivate window\b",
    r"\b1password\b", r"\bbitwarden\b", r"\bkeepass\b", r"\blastpass\b",
    r"\bdashlane\b", r"\bnordpass\b", r"\bproton pass\b", r"\benpass\b",
    r"\bnet ?banking\b", r"\bonline ?banking\b", r"\binternet ?banking\b",
    r"\bcredit card statement\b", r"\baccount summary\b",
    r"\bsign ?in\b.*\bbank\b", r"\bupi pin\b", r"\botp\b",
    r"windows security", r"user account control",
]

# Matched case-insensitively against the browser address bar, when we can read it.
EXCLUDED_URL_PATTERNS = [
    r"\bnetbanking\b", r"\bonlinebanking\b", r"\bnetsecure\b", r"\bsecure\w*\.bank",
    r"hdfcbank\.", r"icicibank\.", r"onlinesbi\.", r"sbi\.co\.in", r"axisbank\.",
    r"kotak\.", r"yesbank\.", r"idfcfirstbank\.", r"pnbindia\.", r"bankofbaroda\.",
    r"canarabank\.", r"unionbankofindia\.", r"indusind\.", r"rblbank\.",
    r"paytm\.", r"phonepe\.", r"razorpay\.", r"billdesk\.", r"npci\.",
    r"paypal\.", r"stripe\.com/(dashboard|login)", r"chase\.com", r"wellsfargo\.",
    r"bankofamerica\.", r"citibank\.", r"hsbc\.", r"barclays\.",
    r"\bcoinbase\.", r"\bbinance\.", r"\bkraken\.",
    r"accounts\.google\.com/(signin|v3/signin)", r"login\.microsoftonline\.com",
    r"\bvault\b", r"1password\.com", r"bitwarden\.com/#/vault",
]


def is_own_window(app: str | None, title: str | None) -> bool:
    """Jimmy's overlay and timeline windows. Jimmy must never capture itself: with
    the timeline open, it re-captured your old text from Jimmy's own screen, and
    search then ranked that copy above the original moment (D25)."""
    return bool(app and title and Path(app).name.lower() == "electron.exe"
                and title.strip().lower().startswith("jimmy"))


class Exclusions:
    """Default list in code, optional user additions from a plain text file.

    File format: one pattern per line, `exe:name.exe`, `title:<regex>` or
    `url:<regex>`; `#` comments ignored.
    """

    def __init__(self, extra_file: Path | None = None):
        self.exes = set(EXCLUDED_EXES)
        self.titles = [re.compile(p, re.I) for p in EXCLUDED_TITLE_PATTERNS]
        self.urls = [re.compile(p, re.I) for p in EXCLUDED_URL_PATTERNS]
        if extra_file and Path(extra_file).exists():
            self._load(Path(extra_file))

    def _load(self, path: Path) -> None:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            kind, _, val = line.partition(":")
            kind, val = kind.strip().lower(), val.strip()
            if not val:
                continue
            try:
                if kind == "exe":
                    self.exes.add(val.lower())
                elif kind == "title":
                    self.titles.append(re.compile(val, re.I))
                elif kind == "url":
                    self.urls.append(re.compile(val, re.I))
            except re.error:
                continue  # a bad user regex must not take the capture loop down

    def check(self, app: str | None = None, title: str | None = None,
              url: str | None = None) -> str | None:
        """Return a short reason string if this surface is excluded, else None."""
        if is_own_window(app, title):
            return "excluded-self: Jimmy's own window"
        if app and Path(app).name.lower() in self.exes:
            return f"excluded-exe:{Path(app).name.lower()}"
        if title:
            for p in self.titles:
                if p.search(title):
                    return f"excluded-title:{p.pattern}"
        if url:
            for p in self.urls:
                if p.search(url):
                    return f"excluded-url:{p.pattern}"
        return None


# --- face stage ----------------------------------------------------------

YUNET = "face_detection_yunet_2023mar.onnx"
SFACE = "face_recognition_sface_2021dec.onnx"


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a.ravel(), b.ravel()) / (na * nb))


def _blur_region(img: np.ndarray, x: int, y: int, w: int, h: int) -> None:
    """Crush the region to a few pixels, then blur. In place.

    The grid is an absolute pixel count, not a fraction of the box: a relative
    grid leaves a big face with proportionally more structure, which is exactly
    the case that matters. Verified by re-running the detector on the output.
    """
    H, W = img.shape[:2]
    m = int(max(w, h) * config.FACE_BLUR_MARGIN)
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(W, x + w + m), min(H, y + h + m)
    if x1 <= x0 or y1 <= y0:
        return
    g = max(1, config.FACE_BLUR_GRID)
    roi = img[y0:y1, x0:x1]
    small = cv2.resize(roi, (min(g, x1 - x0), min(g, y1 - y0)), interpolation=cv2.INTER_AREA)
    coarse = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    k = max(3, (min(x1 - x0, y1 - y0) // 3) | 1)
    img[y0:y1, x0:x1] = cv2.GaussianBlur(coarse, (k, k), 0)


class FaceStage:
    """Detect, blur, and count distinct faces *within one capture window only*.

    Two things leave this object: a blurred frame and a count with per-window
    ordinals. Nothing else. The vector dict is never serialised, never written,
    never logged.
    """

    def __init__(self, models_dir: Path | None = None,
                 threshold: float = config.FACE_COSINE_THRESHOLD):
        d = Path(models_dir or config.MODELS_DIR)
        self.threshold = threshold
        self.available = (d / YUNET).exists() and (d / SFACE).exists()
        self._vectors: dict[str, list[np.ndarray]] = {}
        if self.available:
            self._det = cv2.FaceDetectorYN.create(
                str(d / YUNET), "", (320, 320),
                config.FACE_SCORE_THRESHOLD, config.FACE_NMS_THRESHOLD, config.FACE_TOP_K)
            self._rec = cv2.FaceRecognizerSF.create(str(d / SFACE), "")

    # Serialising this object would defeat the whole point of the stage.
    def __getstate__(self):
        raise TypeError("FaceStage is ephemeral by design and must never be serialised")

    def __reduce__(self):
        raise TypeError("FaceStage is ephemeral by design and must never be serialised")

    def close_window(self, window_id: str) -> None:
        """Forget this window's faces. The same person tomorrow is a new stranger."""
        self._vectors.pop(window_id, None)

    def reset(self) -> None:
        self._vectors.clear()

    def tracked(self, window_id: str) -> int:
        return len(self._vectors.get(window_id, ()))

    def process(self, bgr: np.ndarray, window_id: str) -> tuple[np.ndarray, int, list[int]]:
        """Return (blurred copy, face count, per-window ordinals).

        The input array is not modified; the returned frame is the only one safe
        to persist.
        """
        out = bgr.copy()
        if not self.available or out.size == 0:
            return out, 0, []

        H, W = out.shape[:2]
        scale = 640.0 / W if W > 640 else 1.0
        small = cv2.resize(out, (int(W * scale), int(H * scale)),
                           interpolation=cv2.INTER_AREA) if scale != 1.0 else out
        self._det.setInputSize((small.shape[1], small.shape[0]))
        try:
            _, faces = self._det.detect(small)
        except cv2.error:
            return out, 0, []
        if faces is None or len(faces) == 0:
            return out, 0, []

        known = self._vectors.setdefault(window_id, [])
        ordinals: list[int] = []
        for row in faces:
            full = row.copy()
            full[:14] = full[:14] / scale  # box + 5 landmarks back to original coords
            x, y, w, h = (int(v) for v in full[:4])
            try:
                crop = self._rec.alignCrop(bgr, full)
                feat = self._rec.feature(crop).copy()
            except cv2.error:
                feat = None
            if feat is not None:
                sims = [_cosine(feat, k) for k in known]
                best = int(np.argmax(sims)) if sims else -1
                if best >= 0 and sims[best] >= self.threshold:
                    ordinals.append(best + 1)
                else:
                    known.append(feat)
                    ordinals.append(len(known))
            _blur_region(out, x, y, w, h)

        return out, len(faces), ordinals
