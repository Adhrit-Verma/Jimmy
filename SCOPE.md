# Scope

What is in, what is deliberately out, and what is owed. `AMBIENT_LAYER.md` is the
authority; this file tracks where the build currently stands against it.

The spec is explicit that it is "the source of truth for what to build and, just
as importantly, **what not to build**." Most entries below are in the second
column on purpose.

---

## Stage 1 — in scope, and built

- Active window identity (exe + title) via Win32.
- Screen frames every 2 s via DXGI pull capture, with a perceptual-change gate.
- Exact window text via UI Automation, including waking Chromium's accessibility.
- Ephemeral face stage: detect, differentiate within a capture window, blur
  before write, count only.
- Exclusion list covering password managers, banking, and private windows.
- Mic audio, VAD-gated, transcribed locally with hallucination filtering.
- SQLite + FTS5 over both screen text and speech.
- Blurred thumbnails on disk.
- `doctor` / `run` / `search` / `stats` CLI.

## Stage 1 — deliberately NOT built

| Not built | Why |
|---|---|
| Any UI | Stage 1's acceptance is explicitly "no UI at all". |
| Any LLM call | The gate is the product; it gets built against real data at Stage 3. |
| A second memory store | Jimmy is the brain. Reuse its memory and RAG at Stage 2. |
| A second LLM client | Same reason. Nothing here instantiates one. |
| `faces` / `people` tables | Their absence *is* the design. |
| Enrolment, naming, cross-window face matching | Non-negotiable 2. Absent code paths, not settings. |
| Alerts about other people's surroundings | Non-negotiable 3. |
| Action execution | Non-negotiable 1: nothing runs without explicit approval. Stage 3+. |
| Multi-monitor capture | Single monitor is enough to prove the pipeline. `--monitor` exists. |
| Retention / pruning policy | Needs a real day's footprint to size. See "Owed". |
| Encryption at rest | Not in the spec. Raise it before this leaves one machine. |

---

## Known gaps

### OCR is inert
`pytesseract` is wired but the Tesseract binary is not installed, so
`ocr_available()` is False and the fallback does nothing. `doctor` reports it as
a FAIL rather than hiding it.

**Lost:** exactly what the spec scoped OCR for — canvas-rendered apps and video.
**Not lost:** normal apps, which UIA covers.

To close it: install Tesseract and put it on PATH. No code change needed.

### Audio pause lags by up to one tick
Resolved policy (D13): audio pauses on excluded surfaces unless another app holds
the mic. What's left is the lag. The decision is made once per 2 s tick, so audio
from just before the pause can still arrive as a finished segment. Another app
holding the mic counts as "a call", so dictation qualifies too.

### Face threshold is untuned
Cosine 0.363 is OpenCV's own SFace reference value, not a measurement from real
footage. On synthetic test faces, two visibly different drawings matched as one
person. Needs tuning against actual webcam tiles before the count is trusted for
anything beyond redaction.

### Capture-window boundary is partly resolved
Idle and max-age boundaries are implemented. "Call end" is not, because nothing
detects a call yet. Revisit at Stage 3.

---

## Owed before the relevant stage

**Before loopback audio is enabled** (`CAPTURE_LOOPBACK = True`):
- A recording indicator.
- A per-call opt-out.

The spec calls these out as far cheaper to design in now than to retrofit. They
are why the flag is off, not merely a nice-to-have alongside it.

**Before Stage 4 (overlay):**
- The Stage 3 GO gate must pass: one replayed hour of real screen history
  producing **≤10 cards**, every one defensible. If it wants to fire more, tune
  the gate and replay. Do not proceed.

**Before this runs unattended for a full day:**
- A retention policy. At ~130 MB/day of thumbnails, disk grows ~4 GB/month.
- A global pause. Stage 4 specifies a hotkey and a "pause for 2 hours" control;
  today the only pause is Ctrl-C.

**Before this leaves one machine:**
- Encryption at rest, and a considered answer on what a backup of this database
  means.

---

## Standing constraints

- **6 GB VRAM.** Whisper int8 uses 347 MiB and the face models run on CPU, so
  there is room — but a vision-language model does not fit and is not the plan.
  Screen becomes text early; only text travels onward.
- **Token budget.** A naive 2 s snapshot is ~1,800 LLM calls/hour. The trigger
  gate is a cost control as much as a taste control. Stage 1's dedup gate already
  skips ~65 % of ticks before anything downstream sees them.
- **Jimmy is the brain.** No second LLM client, no second memory store.
- **DPDP Act.** A face embedding is a biometric template whether or not it is
  persisted. The ephemeral design plus write-time redaction shrinks exposure
  substantially; it does not take it to zero, and the docs should keep saying so.
