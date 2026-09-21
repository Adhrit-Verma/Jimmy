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

## Stage 2 — in scope, and built

- The Jimmy core in `jimmy/` (D14, D16): the one LLM client (NVIDIA,
  OpenAI-compatible, streaming, one warm connection), memory in `data/jimmy.db`,
  and the plugin seam.
- The ambient layer as Jimmy's first plugin: keyword search bounded by time
  phrases ("yesterday", "on Tuesday", "last 20 minutes"), plus a timeline of apps
  and speech when a question names a time but no topic.
- Terminal chat: `python -m jimmy chat` with `/remember` and `/context`, plus
  `ask`, `remember` and `doctor`.
- Offline mode that shows retrieval when there's no key.
- A `web_search` tool slot that honestly reports it has no provider.

## Stage 2 — deliberately NOT built

| Not built | Why |
|---|---|
| FastAPI / local HTTP API | Both halves are Python and call each other directly. The first out-of-process caller is the overlay, so it's Stage 4 (D16). |
| Embeddings / vector search | The spec puts semantic hits in Stage 5. Keyword FTS + time windows cover Stage 2. |
| A web search provider | Deferred to Stage 3 by the human; the slot exists. |
| LLM tool/function calling | Only `ACTION` needs it, and actions are Stage 3 behind approval. Jimmy calls its plugins itself. |
| Automatic memory extraction | Jimmy only remembers what you tell it (`/remember`). Auto-extracting facts from chat is a later call. |
| A local LLM | Proposed in D15, pending a benchmark before Stage 3. |

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

## Possible future changes

Ideas I'd want to make but that are **not decided**. Each needs evidence or a
human call before it moves into a stage. When one is adopted, log it in
`DECISIONS-AND-WHY.md` and delete it here.

**Performance and feel** (from D15):
- **Local 3B LLM as the Tier 1 gate.** Benchmark tokens/s and card quality on the
  4050 first. Adopt only if a short card lands in < 1 s beside Whisper.
- **Local embedding model + vector index** for RAG (e.g. `sqlite-vec` in the same
  SQLite, so there's no second database). Stage 2 shipped without it (D16); the
  spec puts it in Stage 5. Pull it forward only if keyword recall misses.
- **Strip window chrome from captured text.** The first real `jimmy ask` showed
  UI boilerplate ("Minimize Maximize Restore Close", "Back Forward") eating the
  context budget. Drop button-only strings, or common chrome words, before
  they're stored or sent.
- **Pick the default model by measurement** once a key exists: latency to first
  token, and answer quality on real questions (D16).
- **Web search provider** for `TIP` cards, when Stage 3 shows the search volume.
- **Prefetch retrieval** when the gate first suspects a card, so context is
  ready before the cloud call.
- **One warm HTTP/2 connection** to the NVIDIA API, reused, to skip the TLS
  handshake on every call.
- **Stream every cloud response** into the overlay token by token.
- **Overlay reacts before the answer does:** listening → thinking → streaming,
  with animations on `transform`/`opacity` only (GPU-composited, 60 fps).
- **Battery mode.** On battery, drop OCR and the local LLM, stretch the tick
  interval, and lean on the cloud. Always-on GPU drains a laptop.

**Capture quality:**
- **Adaptive UIA budget.** Today it's a fixed 0.6 s / 1200 nodes. Grow the budget
  for text-heavy windows if replay shows text being lost.
- **Event-driven capture.** Subscribe to UIA focus/text-changed events instead of
  polling every 2 s, so capture fires when something happens, not on a clock.
- **Proper resampling.** 48→16 kHz uses a box filter today. Switch to a real
  low-pass if transcription quality demands it.
- **Speaker diarization** and the spec's face→voice "speaker in tile 2" assist.
- **Call detection** as a capture-window boundary (D6's remaining open piece).
  It could reuse the mic-in-use signal from D13.

**Privacy and ops:**
- **Tighten the audio-pause lag** (D13): poll exclusion state faster than the
  2 s tick.
- **Retention policy** sized from a real day. Probably: keep text forever, age
  out thumbnails.
- **Encryption at rest** before this ever syncs or backs up anywhere.
- **Recording indicator + per-call opt-out**, required before loopback is enabled.

**Code health:**
- **Split `tests/test_stage1.py`** by stage once Stage 2 adds its own checks.
  Still no framework unless it's needed.

---

## Standing constraints

- **6 GB VRAM.** Whisper int8 uses 347 MiB and the face models run on CPU, so
  there is room — but a vision-language model does not fit and is not the plan.
  Screen becomes text early; only text travels onward.
- **Token budget.** A naive 2 s snapshot is ~1,800 LLM calls/hour. The trigger
  gate is a cost control as much as a taste control. Stage 1's dedup gate already
  skips ~65 % of ticks before anything downstream sees them.
- **Jimmy is the brain.** No second LLM client, no second memory store. The one
  client is `jimmy/llm.py`, enforced by `test_only_one_llm_client`.
- **Captured text leaves the laptop when you ask a question.** Up to 6,000 chars
  of retrieved context per question go to NVIDIA once a key is set (D16).
  Exclusions keep sensitive surfaces out; everything else is fair game, so
  `/context` exists.
- **DPDP Act.** A face embedding is a biometric template whether or not it is
  persisted. The ephemeral design plus write-time redaction shrinks exposure
  substantially; it does not take it to zero, and the docs should keep saying so.
