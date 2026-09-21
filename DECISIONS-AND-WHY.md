# Decisions and why

Append-only. Each entry records what was chosen, what it was chosen over, and the
evidence. When a decision is overturned, add a new entry that supersedes the old
one rather than editing history — the reasoning that was wrong is worth keeping.

Decisions inherited from `AMBIENT_LAYER.md` (UIA before OCR, text-only to the
model, Jimmy as the brain, the four non-negotiables) are not restated here. This
file covers calls made while building.

---

### D1 — Python 3.12, not the system 3.14
**Stage 1 · settled**

The machine's default is 3.14. The whole stack this needs — CTranslate2,
onnxruntime, comtypes, the Rust-built capture wheel — lags a new CPython release
by months. Building on 3.14 would have meant sourcing wheels or compiling, for no
benefit.

`.venv\` is 3.12.10. Every command in the docs uses `.\.venv\Scripts\python.exe`
explicitly rather than a bare `python`, so nobody picks up 3.14 by accident.

---

### D2 — DXGI desktop duplication, pulled, not `WindowsCapture`'s callback
**Stage 1 · settled**

`windows-capture` exposes two APIs: `WindowsCapture` (event-driven, fires
`on_frame_arrived` at display refresh) and `DxgiDuplicationSession` (pull).

We want a frame every 2 s. The push API would deliver ~120 frames in that window
and we would throw away 119. Pull asks for exactly what we need.

Measured: 1920×1080 BGRA in ~7–14 ms per `acquire_frame`. Returning `None` when
the desktop has not changed is a free first-level change gate, on top of dhash.

Note for future readers: the method is `acquire_frame(timeout_ms)`. There is no
`capture()`, despite what the class name suggests.

---

### D3 — Wake Chromium's accessibility engine deliberately
**Stage 1 · settled · load-bearing**

The spec's premise is that UIA gives exact text where macOS gets OCR guesses.
That premise nearly failed: a live Electron window walked **24 nodes / 31
characters**. Useless.

Chromium keeps accessibility off until an assistive technology asks. Once woken,
the same window walked **317 nodes / 4,784 characters**. Since browsers and
Electron apps are most of a working day, UIA without this is not worth having.

`screen.wake_accessibility()` sends `WM_GETOBJECT` with `OBJID_CLIENT` once per
window — the same signal a screen reader sends. `SendMessageTimeoutW` with
`SMTO_ABORTIFHUNG` and a 200 ms timeout, so a hung app cannot stall the loop.

**The cost is real and falls on the observed app**, which now maintains an
accessibility tree. Accepted: it is the price of exact text, and every screen
reader charges it.

*Discovered by accident* — an early probe woke the app, and the next probe's
"before" measurement was already the woken number. Worth remembering when
benchmarking anything stateful.

---

### D4 — UIA walk budget: 1200 nodes, depth 30, 0.6 s
**Stage 1 · settled · supersedes the initial 400 / 12 / 0.3 s**

The first guess capped depth at 12. Chromium maps the DOM deep and 12 cut the
page content off entirely — the cap was silently discarding exactly the text the
whole approach exists to get.

Measured on a live Electron window: 317 nodes, ~230 ms, `.Name` costing ~0.2 ms
per node. The earlier "5 ms/node" reading was one-time `ControlFromHandle` setup
being amortised over too few nodes.

0.6 s is under a third of the 2 s interval, which leaves the loop slack. Caps on
node count, depth and wall clock are all crude; adaptive budgeting is deferred
until replay shows real windows losing text that matters.

---

### D5 — Whisper output is filtered, not trusted
**Stage 1 · settled**

Measured on this machine with `distil-small.en`:

| Input | Decoded as |
|---|---|
| 1.5 s of digital silence | `"you"` |
| 2 s of white noise | `"Thanks."` |

VAD does not catch everything, and an unfiltered pipeline would fill the corpus
with utterances nobody said — then hand them to the Stage 3 gate as evidence. A
phantom quote is worse than a missed one.

Four filters, cheapest first: an RMS floor (120) so near-silence is never decoded
at all; the decoder's own `no_speech_prob` (> 0.6 drops) and `avg_logprob`
(< -1.0 drops); and a blocklist for the stock hallucinations that pass both, only
ever matched against a whole short transcript, never a substring of a real
utterance.

Do not loosen these without recordings that justify it.

---

### D6 — One capture window per app, expiring on idle
**Stage 1 · settled · this is `AMBIENT_LAYER.md` open question 2**

The spec leaves the capture-window boundary open and notes it is the only tunable
that changes behaviour. It offers app switch, call end, or a fixed interval.

**First attempt — close on every app switch — was wrong.** A 30 s run produced
4 windows for 4 frames: alt-tabbing minted a new window per captured frame, so
the face dict was thrown away before it could ever tell two people apart. The
mechanism was intact and the lifetime made it pointless.

**Now:** one live window per app, kept alive while you keep returning to it. It
closes after `WINDOW_IDLE_S` (120 s) unfocused, or `WINDOW_MAX_S` (15 min) total.
`last_hash` is per-window, so returning to an untouched app does not re-write the
same screen.

This matches the intuition that a capture window is *a stretch of working in one
app*, and it survives alt-tabbing during a meeting — the case face
differentiation exists for.

Still open: "call end" as a boundary is not implemented, because nothing detects
a call yet. Revisit at Stage 3.

---

### D7 — Blur strength set by re-detection, not by eye
**Stage 1 · settled**

The first `_blur_region` pixelated to a grid **proportional** to the box
(`size // 16`). It looked convincing. The detector disagreed: re-running YuNet on
the blurred output still found a face, and eyes and mouth survived as distinct
shapes.

A relative grid is wrong precisely where it matters — a larger face keeps
proportionally more structure. Swept absolute grids against re-detection, on the
raw array and after the JPEG round-trip that is what actually lands on disk:

| grid | margin | re-detected | verdict |
|---|---|---|---|
| 16 | 0.18 | 0 | eyes and mouth clearly visible |
| 8 | 0.20 | 0 | structure still readable |
| 6 | 0.25 | 0 | faint structure |
| **4** | **0.25** | **0** | **warm blob, no features — chosen** |
| 3 | 0.30 | 0 | nearly gone; loses the "someone was here" cue |

Grid 4 with a 0.25 margin, `INTER_LINEAR` upscale and a Gaussian at `size//3`.
That keeps the thumbnail useful for the Stage 5 recall timeline — you can tell a
person was present — while the features are gone.

`test_blur_defeats_redetection` asserts this against the detector and after JPEG
compression. **Never tune this by looking at it.**

---

### D8 — Loopback audio off by default
**Stage 1 · settled**

The spec's legal note asks for a recording indicator, a per-call opt-out and
mic-only as the default for calls, and observes these are far cheaper to design
in now than to retrofit.

`CAPTURE_LOOPBACK = False`. The code path exists and works — four loopback
devices enumerate on this machine — but recording the far end of a call is a
consent problem, not a feature flag. The recording indicator and per-call opt-out
are **not built** and are logged in `SCOPE.md` as owed before loopback is enabled.

This is `AMBIENT_LAYER.md` open question 3, answered conservatively and reversibly.

---

### D9 — Screen exclusions do not currently pause audio
**Stage 1 · superseded by D13**

Exclusions suppress screen capture. Audio keeps recording while a banking page or
password manager is focused.

Both options are defensible and neither is obviously right:

- **Suppressing audio too** risks silently dropping a meeting because someone
  checked their balance in another tab mid-call.
- **Leaving it** means the mic is live while a surface we deemed too sensitive to
  screenshot is on screen — someone reading an OTP aloud would be transcribed.

Left as-is for Stage 1 because dropping meeting audio is the louder failure, but
this is a real gap and it is a policy question, not a technical one.

---

### D10 — One connection, one lock, for the store
**Stage 1 · settled · deliberate ceiling**

`Store` puts a single SQLite connection behind one `RLock`, with WAL and
`synchronous=NORMAL`. Writes run at a handful per second — one screen tick every
2 s plus occasional transcripts — so contention is not real.

Marked in the code as the ceiling it is. Split per-table or move to a dedicated
writer thread only if a profile says the lock is the bottleneck.

---

### D11 — `evidence` column is TEXT, not JSON
**Stage 1 · settled · minor deviation from spec**

`AMBIENT_LAYER.md` writes `evidence JSON`. SQLite gives an unrecognised type name
NUMERIC affinity, which would coerce numeric-looking payloads. Declared `TEXT`;
content is still JSON.

---

### D12 — Tesseract not installed; OCR ships inert
**Stage 1 · accepted gap**

`pytesseract` is installed but the Tesseract binary is not on this machine, so
`ocr_available()` returns False and the fallback is a no-op. `doctor` reports it
as a FAIL rather than hiding it.

UIA covers normal apps, so this does not block Stage 1's acceptance. What is lost
is exactly what the spec scoped OCR for: canvas-rendered apps and video. Tracked
in `SCOPE.md`.

---

### D13 — Audio pauses on sensitive surfaces, unless a call is on
**Stage 1 · settled 2026-09-21 by the human · supersedes D9**

Asked directly. Chosen over "always pause", "keep recording" and "keep, but scrub
secrets from transcripts".

When the focused surface is excluded (by exe, title or URL), audio capture
pauses. The in-progress utterance is dropped with it (`VadChunker.reset`), and
the device keeps being drained so nothing overflows. It resumes on the next tick
that lands somewhere safe.

**The call exemption:** if *another* app holds the microphone, the pause is
skipped, so a glance at a bank tab mid-meeting doesn't drop the meeting. The
signal is the Windows consent store
(`HKCU\...\CapabilityAccessManager\ConsentStore\microphone`, `LastUsedTimeStop == 0`),
the same state that drives the taskbar mic icon. It was chosen over a list of
meeting-app exe names because it also catches browser calls (Google Meet), which
a name list cannot. Verified on this machine: it enumerates Teams, Chrome, Edge,
Discord and WhatsApp.

Our own interpreter also appears in that store while we record, so our own
`sys.executable` / `_base_executable` are skipped.

**Known ceilings:**
- "Someone else has the mic" is treated as "a call is on". Dictation or a voice
  recorder qualifies too.
- The decision is made once per tick, so up to one interval (2 s) of audio before
  the pause can still arrive as a finished segment.

A URL-excluded page stays excluded while the same window keeps the same title.
Without that, an unchanged bank tab would skip the tree walk on the next tick,
read as safe, and un-pause the mic.

---

### D14 — The Jimmy brain is built here, in this repo
**Stage 2 · settled 2026-09-21 by the human**

`AMBIENT_LAYER.md` assumes Jimmy already exists, with memory, RAG, an NVIDIA LLM
client and a plugin system, and says to reuse it. Stage 0 found it does not
exist: this folder held only the spec.

Chosen over "separate repo" and "skip the brain and call NVIDIA directly". The
last option would have broken the spec's rule against a second LLM client.

**Consequence:** Stage 2 grows. It now builds a minimal Jimmy core (the NVIDIA LLM
client, a memory/RAG store and the plugin seam) *and* hooks the ambient layer
into it. The spec's rule still holds, just inverted: there is exactly **one** LLM
client and **one** memory store, and they belong to the core, not to the ambient
layer.

---

### D15 — Local decides, cloud speaks
**Stages 2–4 · direction agreed 2026-09-21 · the local-LLM part is PROPOSED, pending a benchmark**

The human asked how much can run on the laptop so it feels instant, with APIs used
only where local would be impossible or slow. The split:

**Local:** all capture (built), redaction (built), the Tier 1 gate (rules,
embeddings, topic-change and question-asked detection), memory writes, RAG
retrieval (FTS5 plus a local vector index), and a small local LLM (~3B, 4-bit)
for "is this worth saying", classification and short `RECALL`/`FOCUS` drafts.

**Cloud (NVIDIA API):** the final card when it needs real reasoning; `TIP`, which
needs the live web; `ACTION` planning; and long syntheses.

**Why:** proactive cards aren't latency-critical, because nobody is waiting on
them, so a card 1–2 s after the moment feels right. "Instant" only matters when
the human asks something. And most ticks never reaching the API is the spec's
token-budget point.

**VRAM budget (estimated):** Whisper 0.35 GB (measured), embeddings ~0.1–0.3 GB,
3B LLM at 4-bit ~2–2.5 GB, desktop/browsers/Electron ~1 GB. That comes to ~4 GB of
6 GB. A 7–8B model does not fit beside Whisper.

**Not yet proven:** the local LLM's speed and quality on the 4050 are estimates.
Benchmark before Stage 3 adopts it as the spec's Tier 1 "small model". See
`SCOPE.md` → Possible future changes.

---

### D16 — Stage 2 shape: Python core, in-process, no FastAPI yet
**Stage 2 · settled 2026-09-21 (language, chat and web search by the human; the rest by me)**

The human answered four questions, one at a time:

| Question | Answer | Over |
|---|---|---|
| Core language | **Python** | Node/TypeScript as the spec wrote it |
| NVIDIA key | none yet; **build against a stand-in** | — |
| Talking to Jimmy | **terminal chat** | internal-only; a local web page |
| Web search | **empty tool slot now, provider at Stage 3** | DuckDuckGo scraping; a keyed API now |

The spec said Node only because it assumed a Node Jimmy already existed (see D14).
Building fresh, Python means one runtime, one database engine, and the strongest
local-AI tooling, which D15 leans on.

**Calls that followed from that, made while building:**

- **No FastAPI in Stage 2.** The spec's `127.0.0.1` API was the bridge between a
  Node Jimmy and a Python sidecar. With both in Python, the ambient layer and
  Jimmy call each other directly, and that satisfies the acceptance ("the sidecar
  gets a useful answer without its own LLM client"). The first real out-of-process
  caller is the Electron overlay, so the local API moves to **Stage 4**.
- **No embeddings in Stage 2.** The spec lists "embeddings for semantic hits"
  under Stage 5. Keyword FTS plus time windows answered every test question here.
  Revisit if real questions miss for lack of synonyms.
- **Memory is its own SQLite file** (`data/jimmy.db`), not new tables in
  `ambient.db`. Captures will one day be pruned by a retention policy; memory must
  not be. Same engine, so it's not "a second kind of store".
- **The ambient layer is a plugin of Jimmy, not the reverse.** `ambient/plugin.py`
  imports from `jimmy`; `jimmy` imports the plugin only inside `Jimmy.default()`.
  So the core has no load-time dependency on capture.
- **Default model `nvidia/nemotron-3.5-lightning-30b-a3b`.** Picked from the live
  model list for speed (MoE, ~3B active). **Unmeasured**: re-decide with real
  numbers once a key exists. It's one env var (`JIMMY_MODEL`) to change.
- **Captured text is untrusted.** It enters the prompt only inside `<context>`,
  after a rule to ignore instructions found there. The test fixture plants an
  "IGNORE ALL PREVIOUS INSTRUCTIONS" in captured text. A prompt rule reduces this
  risk; it does not eliminate it. The hard guarantee has to come from Stage 3's
  approval gate on every action.
- **Offline mode instead of a stub model.** Without a key, `ask` returns what
  retrieval found. That's honest, and it's the most useful thing to look at while
  tuning retrieval.
- **Retry once, never mid-stream.** One retry on 429/5xx or a dropped connection,
  but not after any text has been shown. A retry then would repeat the answer.
- **The key is read from `HKCU\Environment` too.** `setx` only reaches new
  processes; reading the registry means a key set a minute ago works without
  restarting the app. The key's value is never printed.

**What leaves the laptop:** once a key is set, each question sends up to 6,000
characters of retrieved context to NVIDIA. That can include window titles and screen
text from any non-excluded app (a Discord server name showed up in the first real
test). Exclusions still keep banking, password managers and private windows out
entirely. `/context` in chat shows exactly what was sent.
