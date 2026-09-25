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
the desktop has not changed is a free first-level change gate, on top of dhash
(dhash itself was replaced in D18: it was blind to text changes).

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
- **Two methods, not a `stream=` flag.** `ask`/`chat` return `str`;
  `ask_stream`/`chat_stream` return `Iterator[str]`. The first version returned
  `str | Iterator[str]` depending on a flag, so every caller got a type it had to
  guess at (Pylance caught it). The stream variants are plain functions that
  return a generator, so a missing key or failed retrieval raises at the call,
  not on first iteration.
- **The key is read from `HKCU\Environment` too.** `setx` only reaches new
  processes; reading the registry means a key set a minute ago works without
  restarting the app. The key's value is never printed.

**What leaves the laptop:** once a key is set, each question sends up to 6,000
characters of retrieved context to NVIDIA. That can include window titles and screen
text from any non-excluded app (a Discord server name showed up in the first real
test). Exclusions still keep banking, password managers and private windows out
entirely. `/context` in chat shows exactly what was sent.

---

### D17 — Default model: nemotron-3-super-120b, thinking off
**Stage 2 · measured 2026-09-22 · supersedes D16's unmeasured model pick**

D16 picked `nemotron-3.5-lightning-30b-a3b` from the model list, for its name and
its ~3B active parameters. It was the wrong pick. The first live `jimmy doctor`
took **19.4 s** to "reply with one word", and the reply was the model's
reasoning as plain text ("Here's a thinking process: …"), not in `<think>` tags,
so nothing stripped it.

Benchmarked on a realistic Jimmy prompt (a small `<context>` plus a recall
question), streamed, one sample each unless noted:

| Model | First word | Outcome |
|---|---|---|
| nemotron-3.5-lightning (the D16 pick) | 159 s | reasoning leaked into the answer |
| nemotron-3.5-lightning, thinking off | — | no token within 60 s |
| **nemotron-3-super-120b, thinking off** | **0.86–1.15 s** (5 runs) | **clean, correct; 1 run returned empty** |
| nemotron-3-super-120b, thinking on | 2.34–2.57 s (2 runs) | clean (reasoning goes to a separate field) |
| gpt-oss-20b, effort low | 35.8 s | correct, too slow |
| gemma-4-31b, mistral-nemotron, glm-5.3-flash | — | no token within 60 s |
| nemotron-nano-3, gemma-3-12b, mistral-nemo-12b | — | 404 "not found for account" |

**Chosen:** `nvidia/nemotron-3-super-120b-a12b` with thinking off
(`chat_template_kwargs`). `jimmy doctor` afterwards: 0.81 s to first word. With
thinking on, answers to recall questions were the same, just 2.5× slower. So
`config.THINKING` stays off for chat, and is the switch to flip for heavy
syntheses later.

**Three lessons, now in code:**
- **The public model list says what exists, not what your account can use.**
  Three listed models returned 404 for this key, and several never answered.
  `doctor`'s round trip is the real availability check, not the listing.
- **A 200 can be empty.** One run in five came back with no text. `LLM` retries
  an empty answer once (safe, since nothing was shown yet) and then raises
  instead of letting Jimmy go silent.
- **`doctor` must judge the answer, not just receive one.** The old check marked
  a 19 s, reasoning-filled reply "ok". It now requires the exact word back and
  grades latency: < 1.5 s "feels instant", < 3 s "usable", otherwise it fails.

**Live acceptance, same day:** three real questions against the real capture DB
were answered correctly: activity yesterday, screen text about "the sidebar", and
a fact from memory. Each named the time and app, with nothing invented. The data
was a single one-minute capture, so this proves the path, not recall quality over
a real day.

The free tier's behaviour (timeouts, per-account availability) can change
without notice. Re-run the scratch benchmark before trusting these numbers months
from now.

---

### D18 — Fixes from the first real hour
**Stages 1–2 · 2026-09-22 · supersedes the dhash gate (D2's "on top of dhash") and parts of D16's prompt**

The first real session (66 min, 10:17–11:23) was replayed, measured and put to
four recall questions. That showed six problems, all fixed:

**1. The change gate was blind to text.** A 64-bit dhash compares a 9×8
thumbnail of the whole screen. Tested on the hour's own Discord, Teams, VS Code
and Claude screens, scrolling a chat by one message read as "unchanged" in
**7 of 8 cases**. That likely explains most of a 35-minute near-empty stretch
(10:37–11:12) during which the human says they were scrolling and messaging.
**Now:** grey 160×90, and a capture when ≥ 0.25 % of pixels move by more than 12
grey levels. Measured: a one-message scroll moves 2–15 % on real screens (0.6 % on
a thin-text synthetic worst case), a cursor blink 0.01 %, a taskbar clock ~0.02 %.
The first threshold tried, 0.5 %, left the synthetic case too close, so 0.25 %.
**Expect more captures and more storage than the first hour's 2.0 MB/h**, which
was partly low *because* changes were missed. Re-measure.

**2. 44 % of captured text was window chrome** (Minimize, Maximize, Close, Back,
Forward, Filter…, in nearly every capture). **Now:** `ButtonControl` and
`MenuItemControl` names aren't collected; their children still are.

**3. 52 % of captures re-stored near-identical text.** **Now:** each capture
window remembers the lines it has stored, and later captures store only new lines.
The frame row is always written, since it is the timeline. The first capture of a
window still stores the full screen.

**4. Clock times weren't understood.** "Between 10:40 and 11:10" fell back to the
whole morning, and the model confidently described it. **Now:** ranges ("between
X and Y", "10:40–11:10"), points ("at 3pm", "around 10:45" = ±15 min) and bounds
("after 11", "before noon"), combined with a named day. A bare hour from 1 to 7
means afternoon. A time later than now, with no day named, means yesterday.

**5. The model invented and overstated.** It turned an extension's error into
"you were building Discord integration", called a 15-minute uncaptured stretch
"an active conversation", and read first-to-last sightings as continuous use.
**Now:**
- a **coverage** line, first in the context, lists every gap of 5+ minutes as unknown;
- activity lines read "first seen … last seen … N captures";
- prompt rules: state only what the context shows, don't guess intent, an
  on-screen error is something seen not done, never fill a gap, plain text only.

Found while fixing this: **chat history leaked into time-scoped answers.** An
earlier VS Code answer made a later "10:40 to 11:10" answer list VS Code, which
wasn't captured then. Confirmed by asking the same question in a fresh session.
A rule now says facts come only from the current question's context.
**Re-test result:** all four questions answered correctly on the real hour, in
plain text, with gaps named.

**6. A silent mic went unnoticed for 66 minutes.** The default input produced
near-silence the whole hour. Diagnosed: Windows privacy allows access, every
input device read near-zero, and with the human speaking during `ambient doctor`
the headset mic peaked at **9,678**. So the mic works; the hour was simply quiet,
with noise suppression gating the room. Near-silence can't be told apart from a
dead mic, so nothing claims it's broken. **Now:**
- `ambient doctor` runs a 3-second "speak now" test on the mic capture will actually use;
- capture prints once after 10 minutes with nothing speech-loud, and again when sound returns;
- `MIC_DEVICE` in `ambient/config.py` picks an input by name, e.g. the laptop's
  "Microphone Array" when no headset is worn;
- a mic that fails to *open* is now printed. It used to be stored in a field
  nobody read.

**Measured in the hour (old gate):** 82 frames from ~1,981 ticks, 2.0 MB/h
(26 KB thumbnails), 200k chars of text, 0 faces, 0 speech, 23 capture windows
(median 3.2 min). Ask latency 3–7 s per question including Python start-up; the
model's first word ~0.8 s.

**Not fixed, noted:** answers from `jimmy ask` pay ~2 s of Python start-up per
question. Chat keeps one process, so it doesn't. Relevant again at Stage 4.

---

### D19 — Stage 3: rules decide whether to look, the model whether to speak
**Stage 3 · 2026-09-25 · answers from the human, one question at a time**

| Question | Answer | Over |
|---|---|---|
| Card types first | **RECALL + FOCUS** | all four now; RECALL only |
| Tier 1 | **local rules** | a local 3B LLM (D15 stays proposed); cloud decides all |
| Speech languages | **English + Hindi/Hinglish** | English only |

**Tier 1 (`ambient/gate.py`), no LLM:**
- A *moment* is a stretch in one window (app + title). **RECALL is considered
  only when a moment ends**, as the spec requires, if it lasted ≥ 60 s with
  ≥ 200 chars. It takes up to 6 distinctive words and looks for an earlier
  moment elsewhere, ≥ 30 min old, sharing ≥ 2 of them by 6-letter stem.
  "Distinctive" means the word is in > 0 % and ≤ 3 % of all *earlier* text
  blocks, and not on a small generic list.
- A **question heard aloud** (ends in "?", 4+ words) runs the same lookup.
- **FOCUS needs a stated intent** (`jimmy focus "…"`); Jimmy never guesses it.
  It fires after 10 min with nothing on screen related to the intent, once per
  drift, and never again within 45 min of a FOCUS card.
- Hard limits before any cloud call: ≤ 4 cards per rolling hour, ≥ 10 min
  between cards, ≤ 20 candidates/h, no repeats of an earlier item, and a 30 min
  cooldown after a dismissal (wired at Stage 4).
- Replay uses the same class, and every search and rarity count is bounded to
  before the moment, so a replayed card could have fired live.

**Tier 2 (`jimmy/cards.py`):** the one LLM client, thinking on (cards aren't
latency-bound), JSON out: silence or one line of ≤ 7 words. A RECALL line must
name the concrete earlier thing and when. Anything malformed or too long is
silence.

**Found while building, and fixed:**
- **With thinking on, this model writes its reasoning into the reply**, and at
  400 tokens it ran out before the JSON: 2 of 7 decisions were "unparseable".
  Now the last JSON object is taken and the budget is 1,500.
- **Generic words matched moments** ("open/close", "file/python",
  "forward/enter"): 71 minutes of history is too little for rarity alone. So
  there's a generic list plus stem-dedup ("responded/response" = 1).
- **FOCUS nagged:** the same nudge 3× in 46 min. Now one per 45 min.
- **A vague card fired** ("Same backend focus as Adhrit's profile") and its gap
  blocked a better one. The prompt now requires a concrete thing and a when.
- **The free tier returned 503 "overloaded"** in 2 of 4 replays. The card engine
  waits 5 s and tries once more.
- **Speech credited to the user:** "you spoke about…" came from a video playing
  through the speakers. Snippets are now "heard near mic", with a prompt rule.
  Not fully fixed: one answer still guessed "with someone nearby".

**Whisper → `large-v3-turbo`, language auto-detect.** Measured against
distil-small.en and small on TTS clips: English identical and perfect; turbo
+1 GB VRAM, 4 s in 0.6 s. The Hinglish test was **inconclusive**: an English TTS
voice reading romanized Hindi was detected as English by all three. Real Hindi
accuracy is unverified; Hindi comes out in Devanagari, so an English-word search
won't find it.

**Replay on real history (1.18 h, two sessions of 25 + 46 min):** 5 candidates,
2 cards ("Same resume review as Tuesday 15:00", "Same Node.js backend course
as Tue 15:00"), 3 silence, 2 held by the gap. **GO on count.** Still owed: the
human's judgement that each card is defensible, and one continuous recorded
hour, which the spec asks for.

---

### D20 — Card decisions run on a local model (Ollama); the model picks, code writes
**Stage 3 · 2026-09-25 · asked for by the human · amends D19's Tier 2**

The human asked to fix the open issues with a local model via Ollama. Ollama
0.32.13 was already installed with qwen2.5 3B, 7B and 14B. It speaks the same
OpenAI-compatible API, so this is **the same client class with a second
endpoint** (`jimmy.llm.local_llm()`), not a second client. Invariant 7 holds
in spirit: one client implementation; cloud and local are two endpoints.

**The 11 real candidates from replay, through each model:**

| Approach | Model | Per decision | Outcome |
|---|---|---|---|
| model judges + writes the line | cloud super-120b, thinking | 3–19 s | 5 cards, sensible; 1 unparseable |
| same | qwen2.5:3b | ~0.8 s | 1 card; misses the good RECALL |
| same | qwen2.5:7b | 2–4 s | 10 cards; **"Same error as Tuesday's Teams chat" ×5, the prompt's own example** |
| examples removed + grounding check | qwen2.5:7b | 2–4 s | grounded words, **invented times** ("three years ago" for 3 days) |
| model picks, code writes, multi-criteria prompt | qwen2.5:3b / 7b | 1 / 2 s | silence on ~all; 3B's own reason said "unrelated" and it still chose silence |
| **one plain question per call, code writes** | **qwen2.5:3b** | **~1 s, 3.3 GB VRAM** | **agrees with the cloud** on every FOCUS; RECALL "Same Sunandha UI/UX resume as Tue 15:02" |
| same | qwen2.5:7b | 2–5 s | missed that RECALL; slower |

**What changed, and why each step:**
1. **The model never writes the card.** It answers a typed question: for
   FOCUS, `{"related": bool}`; for RECALL, per earlier item, `{"same": bool,
   "thing": "1-3 words copied from it"}`. Code composes "Same ⟨thing⟩ as
   ⟨Tue 15:02⟩", where the thing must occur in that evidence item and the time
   is its real timestamp, or "Back to: ⟨intent's own words⟩". Nothing on a card
   can be invented.
2. **One question per call.** Asked to weigh "helpful, supported, not already
   in mind" at once, small models defaulted to silence against their own
   reasoning. One yes/no each, they answer correctly. Restraint now comes from
   Tier 1's limits, not from the model's mood.
3. **The app name is not a thing.** "Same Claude as Tue 15:00" was dropped:
   same app ≠ same thing. Checked in code and in the prompt.
4. **qwen2.5:3b is the default** (`LOCAL_MODEL`): best agreement, fastest,
   fits beside Whisper turbo (~1 GB). `CARD_ENGINE = "cloud"` switches back to
   super-120b with thinking. Chat answers stay on the cloud model.

**What this fixes:** screen text no longer leaves the laptop for card
decisions; free-tier 503s and empty answers no longer affect cards; invented
words and times are impossible by construction.

**What it doesn't fix:** speech attribution (the mic hears videos). That needs
diarization, not a bigger model. Real Hindi accuracy is still unverified.

**Final replay (1.18 h, local 3B):** 5 candidates → **1 card**, "Same Sunandha
UI/UX resume as Tue 15:02". With a stated intent: +2 FOCUS "Back to: build the
Jimmy stage 3", then held by the 45-min rule. GO on count; review owed (D19).

Ollama unloads an idle model after ~5 min, so the first card after a pause
takes ~10 s to load. Fine for cards, which aren't latency-bound, and it frees
VRAM when idle.

---

### D21 — Jev (TypeSafe AI): where it would fit, and what it would cost
**Stage 3+ · 2026-09-25 · PROPOSED: needs the human's decision and an API key**

Jev (TypeSafe AI, early access 2026-09-15) is a "System One" model: state +
typed questions in, typed answers with **calibrated probabilities** out, in
one pass. Primitives: *Noul* (yes/no → probability), *Choice* (option +
per-option probabilities + confidence), *Score*. Several questions per request,
at `POST https://api.typesafe.ai/v1/systemone`. Hosted only. TypeSafe says it
doesn't train on customer data; zero retention is enterprise-only.

**D20 already shaped Tier 2 the way Jev works:** typed questions in, decisions
out, code writes the words. Jev would slot in behind `CardEngine` as a third
endpoint, with no other change.

**Where it would help, most useful first:**
1. **Tier 2 as calibrated probabilities.** `same` and `related` become
   P(yes). One threshold (e.g. speak at P ≥ 0.8) replaces prompt tuning, and
   the ≤ 10 cards/hour GO gate gets tuned by moving a number in replay.
2. **Batched evidence reranking.** One request scores all earlier items for
   "same thing?" instead of 3 sequential local calls.
3. **Speech attribution.** A Choice (user / someone in the room / media
   playback) per segment, with confidence, so low-confidence speech is never
   credited to the user.
4. **Memory confidence.** Grade remembered facts, as the open-source
   `jevmory` does.

**Costs and risks:** screen text would leave the laptop again, to a third
party (D20 just brought card decisions home). It's early access, with no
published latency, rate limits or processing region. It can't write text, so
chat stays on the LLM. And it's a new key and account.

**Proposed if wanted:** an optional `CARD_ENGINE = "jev"`, compared in replay
against local 3B on agreement and calibration, sending only the candidate's
bounded "now" and evidence (≤ 4.5k chars), never raw captures.
