"""Tunables for the ambient layer.

Every value here is a calibration knob. The defaults are reasoned starting points,
not measured truths -- real hardware drifts and real footage disagrees with papers.
Tune against recordings, then record what you learned in DECISIONS-AND-WHY.md.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("JIMMY_AMBIENT_DATA") or ROOT / "data")
MODELS_DIR = Path(os.environ.get("JIMMY_AMBIENT_MODELS") or ROOT / "models")
DB_PATH = DATA_DIR / "ambient.db"
THUMB_DIR = DATA_DIR / "thumbs"
EXCLUSIONS_FILE = DATA_DIR / "exclusions.txt"  # optional user additions, one pattern per line

# --- screen ---------------------------------------------------------------
FRAME_INTERVAL_S = 2.0
DHASH_SIZE = 8               # 8 -> 64-bit hash
DHASH_MAX_DISTANCE = 6       # <= this many differing bits counts as unchanged; skip the frame
THUMB_WIDTH = 640
THUMB_JPEG_QUALITY = 70

# --- text extraction ------------------------------------------------------
# Measured on a live Electron window: 317 nodes / 4.8k chars / ~230 ms. Chromium
# maps the DOM deep, so depth 12 cut the page off entirely. A 0.6 s budget is
# under a third of the 2 s interval, which leaves the loop plenty of slack.
UIA_MAX_NODES = 1200         # hard ceiling on the foreground-window tree walk
UIA_MAX_DEPTH = 30
UIA_BUDGET_S = 0.60          # abandon the walk past this, whatever we have is what we get
UIA_MIN_CHARS = 40           # below this, the window is probably canvas-rendered -> try OCR
OCR_ENABLED = True           # silently inert if the Tesseract binary is absent

# --- face stage (ephemeral; see AMBIENT_LAYER.md Stage 1b) ----------------
FACE_SCORE_THRESHOLD = 0.7
FACE_NMS_THRESHOLD = 0.3
FACE_TOP_K = 50
FACE_COSINE_THRESHOLD = 0.363  # OpenCV's own SFace reference value -- tune against real footage
FACE_BLUR_MARGIN = 0.25        # expand the box before blurring; detectors clip ears and chins
# Absolute pixel grid the face is crushed to before blurring. Swept against
# re-detection: a size-relative grid left ~11px of structure and YuNet still
# found the face in the saved artifact. At 4 the features are gone but a warm
# blob remains, which is what the recall timeline actually needs.
FACE_BLUR_GRID = 4

# --- capture window boundary (AMBIENT_LAYER.md open question 2) ----------
# One window per app, kept alive while you keep coming back to it. Closing on
# every app switch was the first attempt and it was wrong: alt-tabbing minted a
# new window per frame, so the face dict was discarded before it could tell two
# people apart. A window now dies from neglect or old age, not from a glance
# elsewhere. This is still the tunable that most changes behaviour.
WINDOW_IDLE_S = 120          # unfocused this long -> the window closes, faces forgotten
WINDOW_MAX_S = 15 * 60       # hard ceiling even if the app never loses focus

# --- audio ----------------------------------------------------------------
SAMPLE_RATE = 16000          # what both WebRTC VAD and Whisper want
CAPTURE_MIC = True
CAPTURE_LOOPBACK = False     # default off: recording the far end of a call is a consent problem
VAD_AGGRESSIVENESS = 2       # 0..3, higher = more aggressively calls things non-speech
VAD_FRAME_MS = 30            # WebRTC VAD accepts 10, 20 or 30 only
VAD_SILENCE_MS = 700         # trailing silence that closes a segment
SEG_MIN_MS = 400             # shorter than this is a cough, not a sentence
SEG_MAX_MS = 20000           # force a cut so one monologue cannot grow unbounded
WHISPER_MODEL = "distil-small.en"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "int8"
WHISPER_FALLBACK_MODEL = "small.en"

# Whisper invents text when handed non-speech: measured here, silence decoded as
# "you" and white noise as "Thanks." VAD lets some of that through, so the
# decoder output is filtered too. Loosen only with recordings to justify it.
MIN_SEGMENT_RMS = 120.0      # int16 RMS; below this the segment is never decoded
NO_SPEECH_MAX = 0.6          # drop a decoded segment above this no-speech probability
AVG_LOGPROB_MIN = -1.0       # drop a decoded segment the model is this unsure of
