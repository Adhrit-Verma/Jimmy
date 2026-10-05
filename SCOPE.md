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
- A retention policy. The first hour measured 2.0 MB/h under the old gate (~0.5
  GB/month at 8 h/day); the finer D18 gate will capture more. Size it from the
  next run. The human plans a 500 GB external SSD, so capacity comes first and
  optimisation after.
- A global pause. Stage 4 specifies a hotkey and a "pause for 2 hours" control;
  today the only pause is Ctrl-C.

**Before this leaves one machine:**
- Encryption at rest, and a considered answer on what a backup of this database
  means.

---

## Stage 3 — built, and deliberately NOT built

Built (D19): Tier 1 local rules (moments, RECALL on moment end and on questions
heard aloud, FOCUS on stated intent, hard limits), Tier 2 cloud decision (≤ 7
words), live console cards, `ambient replay`, `jimmy focus`, and multilingual
Whisper (large-v3-turbo).

| Not built | Why |
|---|---|
| TIP cards | Need a web search provider; the human chose to add it after the gate passes. |
| ACTION cards | Need an approval flow; non-negotiable 1. After the gate passes. |
| A local LLM in Tier 1 | Tier 1 stays rules. The local model (D20) is Tier 2 only. |
| Jev (TypeSafe AI) | Proposed (D21): calibrated Tier 2 probabilities, but hosted-only, early access, and screen text would leave the laptop. Needs the human's call and a key. |
| Dismissing a card | No UI yet. `Gate.dismissed()` exists; Stage 4's overlay calls it. |
| Telling the user's voice from the room | The mic hears videos and calls; needs diarization. |

---

## Stage 4 — built, and deliberately NOT built

Built (D23): the Electron overlay (pill + cards, Omi-style, React + Tailwind +
Motion + Lucide), the `127.0.0.1` API it talks through, Pause 2h, Ctrl+Alt+J,
card dismissal wired to the gate's cooldown.

| Not built | Why |
|---|---|
| Multi-monitor | Primary display only; enough to use and judge cards. |
| Chat in the overlay | `jimmy chat` covers it; a panel is a separate design. |
| Settings UI, auto-start, installer | Not in the spec's Stage 4; add when it's used daily. |

---

## Stage 5 — built, and deliberately NOT built

Built (D24): hybrid keyword + meaning search (bge-m3, local), a background
indexer, `ambient index` / `ambient search`, the timeline window (day nav,
search, preview, minute scrub strip), and meaning search in `jimmy ask`.

| Not built | Why |
|---|---|
| An ANN / sqlite-vec index | Brute force is fine for weeks of captures; switch when a month-wide query is slow. |
| Retention / pruning | Still owed (see above); it must prune embeddings with their captures. |
| Clicking a timeline moment to "ask Jimmy about it" | A natural next step; chat stays `jimmy chat` for now. |

---

## Voice Q&A (D25) — built, and NOT built

Built: "Jimmy, …" questions from the mic, the evidence + answer panels,
spoken answers (Windows SAPI), typed Ask, Quit.

| Not built | Why |
|---|---|
| A dedicated wake-word engine | Whisper's transcripts are enough; revisit if "Jimmy" is missed often or latency bothers. |
| Neural / Hindi TTS voices | Windows' SAPI voices are English and robotic but need nothing installed. |
| Deleting the 7 self-captured frames | Skipped at read time; deleting data needs the human's say-so. |

---

## Insights and commands (D31) — built, and NOT built

Built: the Insights tab (day map, per-app bars, hour bars, week heatmap, tiles),
usage questions answered in code (`stats`), voice/typed commands (pause, resume,
focus, open, hush), shorter prompts, a switch row on returning to an unchanged
window, small lazy strip thumbnails, and the overlay feedback pass.

| Not built | Why |
|---|---|
| Exact time tracking | Frames are change-driven; time is estimated with a 5-min gap cap. Good to the minute. |
| Categories ("work" vs "social") and goals | Needs the human's own labels; a guessed category would be wrong often. |
| A topic map (clusters of what you worked on) | Possible with bge-m3 vectors already stored; needs a design for naming clusters without a model writing them. |
| Earcons (a chime on "Jimmy") | The mic would hear them; Whisper invents text from tones. |
| Persisting typed questions for suggestions | They're personal; kept in memory for the session only. |
| ~~Voice resume while paused~~ | Built in D46: while paused the mic hears only the name ("Jimmy, resume"), and nothing is stored. |

---

## Autonomy, hands-free, curtain (D32–D34) — built, and NOT built

Built: RESUME / SUGGEST / REMIND / DEADLINE / RECAP cards, learned mutes,
lock and password-box protection, stored page URLs with Open page, drafts to
the clipboard, calendar events via `.ics` after a yes, voice navigation
without the wake word after Jimmy shows something, "show me …" driving the
UI, and the presence-based privacy curtain.

| Not built | Why |
|---|---|
| Battery mode | The human's call (D32): OCR and the local model stay on; performance gets optimised another way. |
| Liveness (a photo of you could lift the curtain) | Needs depth or a challenge; the curtain is against glances, not a lock (D37). |
| Gaze tracking | A plain webcam reads head direction well, gaze poorly; needs a gaze model. |
| Sending drafts, adding events directly | Never: drafts go to the clipboard, events through your calendar's own confirm. |
| A deadline eval set | Needs real evenings; freeze one before tuning, as D22 did for RECALL. |

---

## Fixes from the first real session (D35) — built, and NOT built

Built: one instance at a time, model tool picking with ask-back and honest
"can't", presence and usage answers for the session's missed questions,
scroll falling through to the window in front, wake word in Devanagari/Urdu,
no personal identifiers read aloud, quieter remembered voice, a compact idle pill.

| Not built | Why |
|---|---|
| Clicking or typing into other apps | Scroll is the one input Jimmy sends, on request. Anything more needs its own approval design. |
| Hindi answers spoken in Hindi | Hindi requests are understood (D36), but the Windows voice is English, so answers are in English. |
| Tool picking for questions | Questions route by rules; only unrecognised instructions pay for a model call. |

---

## Performance (D38) — done, and NOT done

Done with equivalence checks: 127.0.0.1 and kept-open local clients, bge-m3 kept
loaded, a 120 s cloud connection opened during evidence gathering, early
"thinking", speech per sentence, quick mic return, single-threaded OpenCV, 5 fps
webcam, identity reuse for steady faces, cheaper UI Automation walk, no idle
animation, paged meaning search, incremental furniture, cheaper history queries,
optimised JPEG, face detection at thumbnail size.

| Not done | Why / what it needs |
|---|---|
| WebP thumbnails (-28 %) | Changes pixels: a blind legibility check at 1280 px and the blur re-detection test on WebP first. |
| float16/int8 vectors, an approximate index | Small recall change (99.5-99.75 % top-k); needed somewhere past month 6 for whole-history questions. Owner's call. |
| A SQL table for line counts (furniture + gate) | D22's precision depends on it: replay must show identical candidates first. |
| Caching UI Automation roots | Stale elements; needs an A/B on woken windows. |
| Cursor polling instead of mouse-move forwarding | The remaining overlay cost (0.3 % idle, 5-10 % while the mouse moves). |
| Capture rate, change gate, Whisper size, skipping face detection | Never without recordings (red team, D18/D19/D5). |

---

## Jimmy as an agent (D42) — built, and NOT built

Built: the agent loop with native tools and full context; multi-step screen tasks
(plan once + risky steps); look at the screen with numbered marks; find controls;
close apps and tabs; the decision log and `jimmy trace`; the frozen real-command eval
(95 %, baseline 71 %); the user wiki in OKF with confirm/delete in the Memory tab;
calls kept by app name.

| Not built | Why / what it needs |
|---|---|
| Whisper hint words from the screen | The agent's matching fixed the eval's mishearings; hint words need real recordings to prove they don't add errors. |
| Clicking controls with no UI Automation pattern | Needs real mouse events: lands wherever the pointer's target is; its own design. |
| Canvas apps (games, some editors) | No controls to number; vision could point at pixels, but acting needs the mouse. |
| OKF for screen history | OKF's own guidance: curated core only; history stays search (a tool). |

## Hands and eyes (D41) — built, and NOT built

Built: every unplaced request picked by the model with the user's lists in
`<state>`; reminders (edit, delete), goals (new), memories (edit, delete) by voice
and in the Memory tab; "listening…" / "heard" / "not taken: why" in the pill;
screen answers that see the picture (two vision models, then text); the virtual
cursor (press, tick, pick, open, type, one action per yes); opening apps by name.

| Not built | Why / what it needs |
|---|---|
| Multi-step tasks ("book the 8:15 train") | Stage (b): how much of a plan to approve at once is the human's call. |
| Real mouse clicks for controls without patterns | Moves the user's pointer and can land elsewhere; needs its own design. |
| A local vision model | None fits beside Whisper and qwen2.5:3b in 6 GB. |
| A stronger vision model | Only two answer for this key; re-probe when the account changes. |
| Picking among same-named controls by position ("the second link") | Ask back, or name it differently; add ordinals if it matters in use. |

## Live: curtain, resting, no-name asks, forget, timers (D39) — built, and NOT built

Built: the curtain follows where you sit (only leaving the picture curtains, in
1.5 s), identity per track, resting looks while you're away (5 s, or on movement),
Jimmy resting while you're away (mic, indexing, own cards), the follow-up window,
eye-contact asks (auto-calibrating zone, lips, request shape, others-talking rule,
"name only"), the wake word anywhere in the first four words, "delete … from
September" with a yes, `ambient forget` / `ambient compact`, compaction while
away, timers on the pill. D40: the guided eye calibration, follow-ups on a call,
"I'm not on a call", the pill saying why eye contact is off on a call, a steady
eye indicator, a fresh timeline after a forget, scrolling through UI Automation.
NOT built (D40): telling a real call from Discord idling in a channel (the
registry can't); scrolling VS Code's editor by UI Automation (it exposes none:
the pointer's wheel still does it).

| Not built | Why / what it needs |
|---|---|
| A "Jimmy" hotword for Whisper | It can make Whisper write the name into noise. Needs recordings of real misses first. |
| A real gaze model (at the camera vs the top of the screen) | None fits beside Whisper in 6 GB without a download; a plain webcam can't tell those apart. |
| Unloading models while away | Whisper reloads in seconds: waking up would be slow. Ollama unloads its own after idle. |
| Tuned `FOLLOW_MIN`, `MOUTH_MOVING`, `GAZE_ZONE` | Measured only on drawn scenes. Tune from the console's "last match" log and real use. |
| Telling a mobile phone call from talking to Jimmy | The far side is inaudible to the laptop. "Name only" is the switch. |
| A retention policy (e.g. pictures older than N months) | The owner's call; `ambient forget "older than 90 days"` does it by hand. |

---

## Possible future changes

Ideas I'd want to make but that are **not decided**. Each needs evidence or a
human call before it moves into a stage. When one is adopted, log it in
`DECISIONS-AND-WHY.md` and delete it here.

**Performance and feel** (from D15):
- **Local 3B LLM as the Tier 1 gate.** Benchmark tokens/s and card quality on the
  4050 first. Adopt only if a short card lands in < 1 s beside Whisper.
- **A vector index** (`sqlite-vec` or ANN) instead of brute force, once history
  spans months (embeddings themselves shipped in Stage 5, D24).
- **Thinking on, per call, for heavy jobs.** Chat runs with thinking off (~1 s
  vs ~2.5 s, D17). Syntheses like "summarise my week" or `ACTION` planning may
  earn the extra 1.5 s. Measure on real questions first.
- **A fallback model** for when the default times out or 404s on the free tier.
  The benchmark saw several listed models do both. Try the next measured model
  rather than failing the question.
- **Keep the model benchmark in the repo**, not just the scratchpad, so D17's
  numbers can be re-measured when the free tier changes.
- **Web search provider** for `TIP` cards, when Stage 3 shows the search volume.
- **Prefetch retrieval** when the gate first suspects a card, so context is
  ready before the cloud call.
- **One warm HTTP/2 connection** to the NVIDIA API, reused, to skip the TLS
  handshake on every call.
- **Stream every cloud response** into the overlay token by token.

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
- **Thumbnail diet** (the human's question on storage): WebP instead of JPEG
  (~30–50 %), at most one thumbnail per ~30 s per window while text keeps flowing
  (~3–10×), smaller previews, and tiers (full 7 days → thinned → text only).
  Decide from real MB/h with the D18 gate.
- **Graceful external drive.** If the data folder's drive is unplugged, pause
  capture and resume when it's back, instead of erroring.
- **Tune the change gate from replay.** 0.25 % is set by a synthetic scroll and a
  cursor blink (D18). Check a real hour for video/animation that captures every tick.
- **Chrome filtering beyond buttons.** Tabs, toolbars and sidebars still repeat
  across captures; "only new lines" now hides most of it. Measure what's left.

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
  gate is a cost control as much as a taste control. Stage 1's change gate skipped
  96 % of ticks in the first real hour (old gate; the D18 gate will skip somewhat
  fewer) before anything downstream saw them.
- **Jimmy is the brain.** No second LLM client, no second memory store. The one
  client is `jimmy/llm.py`, enforced by `test_only_one_llm_client`.
- **Captured text leaves the laptop when you ask a question.** Up to 6,000 chars
  of retrieved context per question go to NVIDIA once a key is set (D16).
  Exclusions keep sensitive surfaces out; everything else is fair game, so
  `/context` exists.
- **DPDP Act.** A face embedding is a biometric template whether or not it is
  persisted. The ephemeral design plus write-time redaction shrinks exposure
  substantially; it does not take it to zero, and the docs should keep saying so.
