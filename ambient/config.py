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
THUMB_WIDTH = 1280           # D27: large enough to read when opened big (was 640; ~2-3x storage)
THUMB_JPEG_QUALITY = 65

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
# D36: the human speaks English and Hindi, nothing else. Detection still runs, but
# only these can win: a segment detected as anything else (it guessed Urdu, Korean,
# Danish on 2026-10-02) is decoded again as whichever of these scored higher.
# Urdu's score counts toward Hindi: spoken, they're one language.
WHISPER_LANGUAGES: tuple[str, ...] = ("en", "hi")
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

# --- insights: where the day went (D31) -------------------------------------
# Frames are written only when something changes, so time is estimated: each
# frame counts until the next, up to this cap. A longer gap is away / idle.
ACTIVE_GAP_S = 300

# --- Jimmy on its own (D32) --------------------------------------------------
# Each of these only touches Jimmy: it notices and shows a card. Anything that
# would act on the world (set a focus, open a page, add an event) waits for a yes.
RESUME_GAP_S = 45 * 60       # back after this long without a capture -> "Left off: …"
SUGGEST_FOCUS_WINDOW_S = 20 * 60   # one window this much of the last N min, no focus set ->
SUGGEST_FOCUS_SHARE = 0.6          # ...offer it as the focus
SUGGEST_FOCUS_EVERY_S = 2 * 3600   # at most one offer this often
RECAP_HOUR = 21              # the day's recap card shows at/after this local hour (once a day)
RECAP_MIN_ACTIVE_S = 30 * 60  # ...if at least this much was on screen
DEADLINE_SCAN_S = 300        # look for deadlines in new text this often
DEADLINE_MAX_DAYS = 45       # a date further out than this is not a deadline worth a card
DEADLINE_CHECKS_PER_HOUR = 20  # local-model yes/no calls, at most
DEADLINE_EVE_HOUR = 17       # the day before: warn at/after this hour; on the day: after 7
MUTE_AFTER_DISMISSALS = 3    # this many dismissals of a card kind in one app (14 days),
MUTE_WINDOW_DAYS = 14        # ...and none used -> that kind stays quiet in that app
NAV_WINDOW_S = 45            # after Jimmy shows you something, "next", "scroll down",
                             # "close" work without saying "Jimmy" for this long (D33)
OFFER_WAIT_S = 30            # "add it?" -> a bare "yes" counts for this long

# --- privacy curtain: presence from your own webcam (D34) --------------------
# Counts faces and reads head direction. Never recognises anyone: no face
# vectors are computed from the webcam, nothing is stored (non-negotiable 2).
PRESENCE = True              # False: no webcam at all
PRESENCE_CAMERA = 0          # OpenCV camera index
PRESENCE_FPS = 4
PRESENCE_MIN_FACE = 0.06     # ignore faces narrower than this share of the frame (far away)
AWAY_S = 6                   # no face this long -> away -> curtain
WATCHED_S = 1.0              # a second face this long -> someone's looking
RETURN_S = 0.6               # one face facing the screen this long -> curtain lifts
CURTAIN_WHEN_AWAY = True
# Someone else looking: "full" curtain only on a sensitive surface (banking,
# password field), as the spec's shoulder-surf warning says; otherwise Jimmy
# hides its own panels and warns in the pill.
CURTAIN_WHEN_WATCHED = "sensitive"   # "always" | "sensitive" | "never"
LOOK_AWAY_S = 0              # >0: looking away this long also curtains (off: reading paper is normal)
# --- your face, remembered (D37): only on "remember my face", DPAPI-encrypted ----
OWNER_MATCH = 0.42           # cosine to your template; OpenCV's same-person line is 0.363, a bit stricter here
STRANGER_S = 2.0             # someone who isn't you, at the screen, this long -> curtain
CURTAIN_WHEN_STRANGER = True
ENROL_FPS = 8                # frames a second while capturing (preview + checks)
ENROL_TIMEOUT_S = 90
ENROL_MIN_LIGHT = 70         # face-region mean grey: darker than this -> "turn on a light"
ENROL_MAX_LIGHT = 210        # brighter -> "too much light on your face"
ENROL_MIN_SHARP = 30         # Laplacian variance of the face crop: below -> "hold still" (motion blur)
ENROL_MIN_AGREE = 0.5        # the straight-on samples must be this alike, or the capture is redone
DARK_FRAME = 12              # mean grey below this = covered lens / dark room -> presence off

# --- ask by voice, answers come to you (D25) --------------------------------
ASK_EVIDENCE = 6             # moments shown beside a spoken answer
LISTEN_WINDOW_S = 8          # after "Jimmy" alone, the next thing said (within this) is the question
VOICE_ANSWERS = True         # read spoken questions' answers aloud (Windows' built-in voice)
VOICE_MAX_CHARS = 220        # read at most this much: the first sentences that fit (D31: was 320)
VOICE_RATE = 1               # SAPI speaking rate, -10..10
VOICE_VOLUME = 55            # 0..100; D35: 100 was too loud. "Jimmy, speak softer/louder" changes it
CONVO_S = 180                # questions this close together are one conversation (D27)
CLARIFY_WAIT_S = 20          # after Jimmy asks "now, or earlier?", wait this long for the reply (D28)
