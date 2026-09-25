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
# Change gate (D18). A 64-bit dhash was blind to text: scrolling a chat by one
# message read as "unchanged" in 7 of 8 real screens. Now: grey 160x90, count
# pixels that moved by more than GATE_PIXEL_DELTA. Measured on real screens:
# one-message scroll 2-15 % of pixels, cursor blink 0.01 %.
GATE_GRID = (160, 90)
GATE_PIXEL_DELTA = 12        # grey levels; below this is compression shimmer
# >= this % of pixels changed -> capture. 0.5 left a synthetic thin-text dark
# chat scroll at 0.6 %, too close to call; 0.25 is 25x a cursor blink (0.01 %)
# and >10x a taskbar clock tick (~0.02 %).
GATE_CHANGED_PCT = 0.25
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
# None = the Windows default input. Otherwise a case-insensitive part of the
# device name, e.g. "Microphone Array" for the laptop mic when no headset is on.
MIC_DEVICE: str | None = None
SILENCE_WARN_S = 600         # say so once if the mic hears nothing speech-loud for this long
CAPTURE_LOOPBACK = False     # default off: recording the far end of a call is a consent problem
VAD_AGGRESSIVENESS = 2       # 0..3, higher = more aggressively calls things non-speech
VAD_FRAME_MS = 30            # WebRTC VAD accepts 10, 20 or 30 only
VAD_SILENCE_MS = 700         # trailing silence that closes a segment
SEG_MIN_MS = 400             # shorter than this is a cough, not a sentence
SEG_MAX_MS = 20000           # force a cut so one monologue cannot grow unbounded
# Multilingual (D19): the human speaks English and Hindi/Hinglish near the laptop,
# and the English-only distil-small.en garbled it. Measured: ~1 GB VRAM, 4 s of
# English in 0.6 s, English output identical. Hindi comes out in Devanagari.
WHISPER_MODEL = "large-v3-turbo"
WHISPER_LANGUAGE: str | None = None   # None = detect per segment; "en" to force English
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE = "int8"
WHISPER_FALLBACK_MODEL = "small"   # multilingual too

# Whisper invents text when handed non-speech: measured here, silence decoded as
# "you" and white noise as "Thanks." VAD lets some of that through, so the
# decoder output is filtered too. Loosen only with recordings to justify it.
MIN_SEGMENT_RMS = 120.0      # int16 RMS; below this the segment is never decoded
NO_SPEECH_MAX = 0.6          # drop a decoded segment above this no-speech probability
AVG_LOGPROB_MIN = -1.0       # drop a decoded segment the model is this unsure of

# --- trigger gate, Tier 1 (Stage 3, D19) -----------------------------------
# Local rules only: no LLM. Every value here is a first guess, tuned by
# `ambient replay` against the <= 10 cards/hour GO gate, not by intuition.
MOMENT_MIN_S = 60            # a moment shorter than this ends without a RECALL look
MOMENT_MIN_CHARS = 200       # ...or with less new text + speech than this
# The earlier moment must be a different sitting (D22). At 30 min, most false
# RECALLs were "the same chat you had open minutes ago", which the blind judges
# rejected as nothing to recall.
RECALL_MIN_AGE_S = 2 * 3600
RECALL_TERMS = 6             # distinctive words taken from a moment
RECALL_MAX_TERM_SHARE = 0.03  # a word in > 3 % of all text blocks is not distinctive
RECALL_MIN_SHARED = 2        # distinctive words an earlier hit must share
# A line seen in this many capture windows is screen furniture (sidebar, friend
# list, own name, buttons), not content, and is ignored for RECALL (D22). The
# blind judges rejected all 21 RECALL candidates; every false card rested on it.
PERSISTENT_LINE_WINDOWS = 3
FOCUS_DRIFT_S = 10 * 60      # off-intent this long -> a FOCUS candidate
# General tools serve any intent, so being in them never counts as drift (D22):
# the judges rejected FOCUS cards fired while the user was in Claude.
FOCUS_NEUTRAL_APPS = {"claude.exe", "code.exe", "windowsterminal.exe", "powershell.exe",
                      "cmd.exe", "explorer.exe", "searchhost.exe"}
FOCUS_REPEAT_S = 45 * 60     # after a FOCUS card, no more FOCUS for this long: one nudge, not nagging
MAX_CARDS_PER_HOUR = 4       # hard cap, rolling hour (the spec's gate is <= 10)
MIN_CARD_GAP_S = 10 * 60     # never two cards closer than this
MAX_CANDIDATES_PER_HOUR = 20  # cap on Tier 2 (cloud) calls, rolling hour
DISMISS_COOLDOWN_S = 30 * 60  # after a dismissal (wired by the Stage 4 overlay)

# --- recall timeline, Stage 5 (D24) -----------------------------------------
INDEX_EVERY_S = 60           # embed new captures for meaning search this often while running
