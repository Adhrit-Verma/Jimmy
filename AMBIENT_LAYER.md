# Jimmy Ambient Layer — build spec

An always-on desktop assistant for Windows 11, built as a subsystem of Jimmy.
Reference product: Omi for macOS. This spec is the source of truth for what to build
and, just as importantly, what not to build.

**Thesis:** continuous capture is commodity. The product is the gate that decides to
stay quiet. In the reference product's own demo reel it speaks six times in an
evening, never more than seven words, and every line lands. Build for that, not for
throughput.

---

## Hard constraints

- **Hardware:** HP laptop, Ryzen 7 7000-series, RTX 4050 with **6 GB VRAM**.
  Transcription and OCR run locally and fit comfortably. A local vision-language
  model does **not** fit alongside them. Therefore: convert screen to *text* early
  (accessibility tree first, OCR second) and send only text to a large model.
- **Token budget:** a snapshot every 2s is ~1,800 LLM calls/hour if built naively.
  The trigger gate is a cost control as much as a taste control.
- **Jimmy is the brain.** Reuse Jimmy's existing memory, RAG, NVIDIA LLM client and
  plugin system. Do not build a second LLM client or a second memory store.

## Non-negotiables

1. **No action executes without explicit user approval.** ACTION cards propose; the
   user confirms. This matches Jimmy's existing rule about self-modification.
2. **Face stage never persists, enrols or names.** See "Stage 1b" below. These are
   absent code paths, not settings that default to off.
3. **No proactive alerts about other people's surroundings.** The system may not
   surface "an unknown person is present in X's video call" or any equivalent
   finding about a third party's environment or behaviour. The face signal feeds
   redaction, counting, diarization assist and shoulder-surf warning only.
4. **Exclusion list ships before first run.** Password managers, banking domains,
   private/incognito windows. Cheaper now than scrubbing six months of history later.

---

## Architecture

```
 SOURCES                        PIPELINE                          OUTPUT

 active window (UIA) ──────┐
 screen frame (2s) ─► REDACT ─┤
 mic + loopback audio ─────┤──► CONTEXT BUS ──► TRIGGER GATE ──► CARD ENGINE ──► OVERLAY
 calendar + clock ─────────┘         │          (local, no LLM)      │          (pill+card)
                                     │                │              │
                                     ▼            ~99% ▼             ▼──► ACTION (approval)
                                SQLite+FTS5       SILENCE        JIMMY CORE
                                                                 (memory/RAG/tools)
```

Python sidecar owns capture, redaction, transcription and the trigger gate, and
exposes FastAPI on `127.0.0.1`. Jimmy (Node) loads it as a plugin. Electron owns the
overlay.

---

## Stage 1 — Context bus

Build this first. No UI at all.

**Tasks**
- Active window + focused control text via UI Automation (`uiautomation`, or FlaUI).
  This is the Windows advantage over the macOS original: exact text, not OCR guesses.
  OCR (Tesseract) is the fallback for canvas-rendered apps and video only.
- Screen frames every 2s via `windows-capture` (GPU path). Skip frames that are
  perceptually unchanged (dhash or similar) before doing any work on them.
- Audio: mic + WASAPI loopback via `pyaudiowpatch`. VAD-gated chunking.
- Transcription: faster-whisper `distil-small.en`, int8, on the 4050.
- Everything lands in SQLite with FTS5.

**Acceptance:** a full working day is captured and queryable by text, and no
unblurred face exists anywhere on disk.

### Proposed schema

```sql
capture_windows(id TEXT PK, opened_at INT, closed_at INT, kind TEXT)
frames(id INT PK, ts INT, window_id TEXT, app TEXT, title TEXT,
       thumb_path TEXT, face_count INT)
text_blocks(id INT PK, frame_id INT, source TEXT /* 'uia' | 'ocr' */, text TEXT)
text_fts  -- FTS5 virtual table over text_blocks.text
audio_segments(id INT PK, ts_start INT, ts_end INT,
               source TEXT /* 'mic' | 'loopback' */, speaker_ord INT, text TEXT)
cards(id INT PK, ts INT, type TEXT, line TEXT, evidence JSON,
      state TEXT /* 'shown' | 'dismissed' | 'acted' */)
```

Note there is no `faces` table and no `people` table. That is deliberate.

## Stage 1b — Face stage (ephemeral differentiation)

Purpose: make redaction possible, and let a moment report *how many* distinct faces
were present without ever learning *who* they are.

**Mechanism**
- Detect with `cv2.FaceDetectorYN` (YuNet), embed with `cv2.FaceRecognizerSF`
  (SFace). Both ship in opencv-contrib, both run on CPU in a couple of milliseconds
  per frame, so neither competes with Whisper for VRAM.
- Vectors live in an in-memory dict keyed by a UUID minted when the capture window
  opens. Compare within that window only, cosine threshold ≈ 0.36 (OpenCV's own
  SFace reference value — tune against real footage).
- When the window closes, drop the dict. The same person tomorrow is a new hash with
  no link to today's.

**Rules**
- The dict is never serialised, never written to SQLite, never logged.
- No enrolment gallery. No name binding. No cross-window comparison.
- Only two things leave the window: the **blurred frame** (faces blurred *before* the
  write, so the stored artifact never contains a face) and a **count plus per-window
  ordinal** ("2 faces: face 1, face 2").

**Consumers:** write-time redaction; meeting attendance count; diarization assist
(pair a voice with a video tile → "speaker in tile 2"); shoulder-surf warning (a face
in your *own* webcam that isn't yours while a password manager or banking page is
focused).

**Open decision:** what closes a capture window — app switch, call end, or a fixed
interval. This sets how long a face stays distinguishable and is the only tunable
here that changes behaviour.

**Legal note:** a face embedding is a biometric template under India's DPDP Act
whether or not it is persisted. The ephemeral design plus write-time redaction
shrinks exposure substantially; it does not take it to zero. Same logic for call
audio — a recording indicator, a per-call opt-out and mic-only as the default for
calls are far cheaper to design in now than to retrofit.

## Stage 2 — Jimmy hookup

FastAPI on `127.0.0.1`; Jimmy loads the sidecar as a plugin. The sidecar can ask
Jimmy a question and receive memory, RAG results, web search and tool access back.

**Acceptance:** the sidecar gets a useful answer from Jimmy without instantiating its
own LLM client.

## Stage 3 — Trigger gate + card engine

**This is the product.** Spend the most time here. It ships to a console log — no UI.

Two tiers:
- **Tier 1 (gate, no LLM):** local rules plus a small model decide *whether* anything
  changed enough to be worth speaking. New app, new topic, a draft going quiet, a
  question asked aloud, a stall on one problem. Hard rate limit, cooldown after a
  dismissal, no repeats within a session.
- **Tier 2 (engine, LLM):** given a surviving delta, return either silence or exactly
  one card — a type, one line, and optional evidence.

**Card types** (from the reference product; the label picks what evidence must be
gathered before speaking):
- `TIP` — claim detection → live web search → three cited sources with publisher,
  headline and date.
- `FOCUS` — requires a model of current *intent*, not current window.
- `ACTION` — tool execution via Jimmy's plugin layer, plus a clarifying question
  before committing.
- `RECALL` — cross-time linking of a person, an earlier conversation and an object.
  Fires after a moment ends, not during it.

**Acceptance / GO-NO-GO:** replay one recorded hour of real screen history. It must
produce **≤10 cards**, and you must be willing to defend every one. If it wants to
fire more, tune the gate and replay — do not proceed to Stage 4.

## Stage 4 — Overlay

Only after the GO gate passes.

Electron (matches the reference product's own Windows port and Jimmy's Node core).
Transparent, always-on-top, `WS_EX_TRANSPARENT` for click-through, per-monitor DPI
awareness, no taskbar entry. A small pill at top-centre plus cards at top-right.
Include a "pause for 2 hours" control and a global pause hotkey.

## Stage 5 — Recall timeline

Mostly free once Stage 1 exists: FTS5 over extracted text, embeddings for semantic
hits, blurred thumbnails on a scrub timeline.

**Acceptance:** answers "what was that thing I saw on Tuesday".

---

## Open questions for the human

1. Jimmy's existing code — the `C:\Code\Jimmy` folder currently reads as empty.
   Confirm the real tree before Stage 1 starts.
2. Capture-window boundary (see Stage 1b).
3. Audio scope for calls: mic only, or system audio too.
