# CLAUDE.md — read this first

Orientation for any Claude session working in `C:\Code\Jimmy`. It exists to stop
you re-deriving things that are already settled. If something here contradicts
the code, the code wins — and fix this file in the same change.

---

## What this project is

The **Jimmy ambient layer**: an always-on desktop assistant for Windows 11.
`AMBIENT_LAYER.md` is the build spec and the source of truth for *what to build
and what not to build*. Everything else, including this file, is downstream of it.

**Thesis:** continuous capture is commodity. The product is the gate that decides
to stay quiet. Build for six good interruptions an evening, not for throughput.

**Current state: all five stages are done, plus voice Q&A (D25):** "Jimmy, …" → an
evidence panel and a spoken answer, with no typing needed. Stage 3 (trigger gate) passed its 5-check
list, blind-judged (D19–D22). Stage 4 is the Electron overlay (D23). Stage 5 is hybrid
keyword + meaning recall and a timeline window (D24). Remaining work lives in
`SCOPE.md` → Possible future changes. The Jimmy core
(the one LLM client, memory, the plugin seam) lives in `jimmy/`, and the ambient
layer is its first plugin (D14, D16). See `TIMELINE.md`.

---

## Keep these docs current

The human asked for this explicitly. When you change code, update the docs the
change actually touches — **applicable ones only**, do not touch all seven by reflex.

| File | Update it when |
|---|---|
| `CLAUDE.md` | the file map, commands, invariants or verified environment change |
| `ARCHITECTURE.md` | a component, dependency or threading boundary changes |
| `DATA-FLOW.md` | the tick path, the audio path or the DB schema changes |
| `DECISIONS-AND-WHY.md` | you make a non-obvious call, or overturn one — append, don't rewrite history |
| `SCOPE.md` | something moves in or out of scope for a stage |
| `TIMELINE.md` | a stage or acceptance gate changes status |
| `README.md` | install steps or user-facing commands change |

Two filenames differ from how they were first asked for: `ARCHITECTURE.md`
(spelling) and `DECISIONS-AND-WHY.md` (`&` is hostile to Windows shells).

---

## Running it

The venv is **Python 3.12**, not the system 3.14 — see `DECISIONS-AND-WHY.md` D1.

```powershell
cd C:\Code\Jimmy
.\.venv\Scripts\python.exe -m ambient doctor          # check every component
.\.venv\Scripts\python.exe -m ambient run             # capture until ctrl-c
.\.venv\Scripts\python.exe -m ambient run --seconds 60 --no-audio
.\.venv\Scripts\python.exe -m ambient search "what was that thing"
.\.venv\Scripts\python.exe -m ambient stats
.\.venv\Scripts\python.exe tests\test_stage1.py       # 15 checks, no framework

.\.venv\Scripts\python.exe -m jimmy doctor           # key, model, endpoint, data
.\.venv\Scripts\python.exe -m jimmy chat             # talk to Jimmy (/context, /remember)
.\.venv\Scripts\python.exe -m jimmy ask "what was I reading yesterday?"
.\.venv\Scripts\python.exe -m jimmy remember "standup is at 10:30"
.\.venv\Scripts\python.exe tests\test_stage2.py       # 14 checks, mocked network

.\.venv\Scripts\python.exe -m ambient replay --dry    # Tier 1 candidates only, free
.\.venv\Scripts\python.exe -m ambient replay          # GO/NO-GO: <= 10 cards in any hour
.\.venv\Scripts\python.exe -m jimmy focus "finish X"  # state an intent (FOCUS cards)
.\.venv\Scripts\python.exe tests\test_stage3.py       # 11 checks, no network
```

`ambient run` runs the gate live and opens the overlay (`--no-cards`, `--no-overlay`).
`ambient run --demo` plays a scripted walkthrough for a screen recording (D28; `ambient/demo.py`).

```powershell
cd overlay; npm install; npm run build   # once, and after any change under overlay/src
.\node_modules\electron\dist\electron.exe . --demo                      # see the UI, no Python
.\node_modules\electron\dist\electron.exe . --demo --snapshot shot.png   # render to a PNG and quit
.\.venv\Scripts\python.exe tests\test_stage4.py   # 5 checks: API, pause, window flags, effect bodies
.\.venv\Scripts\python.exe -m ambient index       # backfill meaning-search vectors (bge-m3)
.\.venv\Scripts\python.exe -m ambient search "consulting application on Friday"   # keywords + meaning
.\.venv\Scripts\python.exe tests\test_stage5.py   # 14 checks: recall, voice ask, router, clarify, screen, commands, self-exclusion, demo
```

Timeline window: pill → **Timeline**, or **Ctrl+Alt+T**. Snapshot it on real data
by serving the API (see `tests/test_stage5.py` for the hooks) and running
`electron . --timeline --snapshot shot.png`.

Without `NVIDIA_API_KEY`, Jimmy runs **offline**: every answer shows what retrieval
found instead of a model reply. That is intended, not a bug. The key is read from
the process environment *or* `HKCU\Environment`, so a fresh `setx` works without
restarting anything. Never read, print or ask for the key's value.

`cv2` prints `net_impl_backend ... Targets are not supported` on import. It is
harmless noise from OpenCV 5's new DNN graph engine; filter it, don't chase it.

---

## File map

| Path | What lives there |
|---|---|
| `AMBIENT_LAYER.md` | the build spec. Read before changing behaviour. |
| `ambient/config.py` | every tunable, with the reasoning inline. Change knobs here, not in code. |
| `ambient/db.py` | SQLite + FTS5 store. Schema, writes, unified search. |
| `ambient/redact.py` | exclusions + the ephemeral face stage. **The sensitive file.** |
| `ambient/screen.py` | DXGI capture, 160×90 change gate, UIA text, OCR fallback, thumbnails. |
| `ambient/audio.py` | WASAPI capture, VAD chunking, Whisper + hallucination filtering. |
| `ambient/bus.py` | the one loop. Capture-window lifecycle lives here. |
| `ambient/__main__.py` | CLI: `run`, `search`, `stats`, `doctor`. |
| `ambient/plugin.py` | the ambient layer as a Jimmy plugin: time phrases → bounded search + activity. |
| `jimmy/config.py` | core tunables: endpoint, model, context budget. |
| `jimmy/llm.py` | **the only LLM client in the repo.** Streaming, one warm connection, `<think>` stripping. |
| `jimmy/memory.py` | Jimmy's memory (`data/jimmy.db`): remembered facts, chat turns, and the safe `fts_query`. |
| `jimmy/core.py` | `Jimmy.ask` (whole answer: `str`) and `Jimmy.ask_stream` (`Iterator[str]`): gather from memory + plugins → bounded context → LLM. The prompt lives here. |
| `jimmy/__main__.py` | CLI: `chat`, `ask`, `remember`, `doctor`. |
| `tests/test_stage1.py` | stage 1 check. Assert-based, no pytest. |
| `ambient/gate.py` | Stage 3 Tier 1: moments, RECALL/FOCUS rules, hard limits, `replay()`. No LLM. |
| `jimmy/cards.py` | Stage 3 Tier 2: typed questions to the local model (default) or cloud; code writes the ≤7-word card. |
| `ambient/ask.py` | D25/D27/D28: wake word, `route()` (chat / screen / recall / clarify / show + follow-ups), `interpret()`, evidence, `Asker` (conversation, ask-back, overlay events), `Voice` (SAPI). |
| `ambient/demo.py` | D28: `ambient run --demo`, scripted questions through the real Asker, for screen recordings. |
| `overlay/src/Answer.jsx` | the answer view: evidence left (best match focused), streamed answer right. |
| `ambient/recall.py` | Stage 5: chunk + index (bge-m3), meaning search, hybrid (RRF) with furniture filter, timeline API reads. |
| `overlay/src/Timeline.jsx` | the timeline window: day nav, search, preview, minute scrub strip. |
| `tests/test_stage5.py` | stage 5 check. A collision-free fake embedding; real HTTP; thumb path traversal. |
| `ambient/api.py` | Stage 4 local API: 127.0.0.1, per-run token, SSE events, pause/resume/dismiss. Stdlib only. |
| `overlay/main.cjs` | Electron main: the transparent click-through window, hotkey, all networking. |
| `overlay/preload.cjs` | the page's only bridge: events in; api / pointer-over-ui out. |
| `overlay/src/App.jsx` | the pill and cards (React + Tailwind + Motion + Lucide). |
| `tests/test_stage4.py` | stage 4 check. Real HTTP on 127.0.0.1, no Electron needed. |
| `tests/test_stage3.py` | stage 3 check. Fake Tier 2 + mocked LLM, no network. |
| `tests/test_stage2.py` | stage 2 check. The real client runs against `httpx.MockTransport`. |
| `models/` | YuNet + SFace ONNX. Committed deliberately; small and pinned. |
| `docs/img/` | README screenshots: the real overlay and model on **invented** pages, never real captures (they hold personal data). |
| `data/` | the capture DB and blurred thumbnails. Never commit. |

---

## Invariants — do not break these

From `AMBIENT_LAYER.md`'s non-negotiables. Each is an *absent code path*, not a
setting that defaults to off.

1. **No action executes without explicit user approval.** Stage 3+, but design for it now.
2. **There is no `faces` table and no `people` table.** `test_store_roundtrip_and_fts`
   asserts their absence. If you find yourself adding one, you have lost the design.
3. **Face vectors never leave RAM.** `FaceStage` refuses to pickle, on purpose.
   Only two things leave a capture window: a blurred frame, and a count + ordinals.
4. **Faces are blurred before the write.** `bus.tick` only ever passes `blurred`
   to `save_thumb`; the clean frame never reaches disk. Proven by
   `test_blur_defeats_redetection`, which re-runs the detector on the saved JPEG.
5. **No proactive alerts about other people's surroundings.** The face signal is
   for redaction, counting, diarization assist and shoulder-surf warning only.
6. **The exclusion list ships before first run.** It already does. Adding capture
   surfaces without checking them against `Exclusions` is a regression.
7. **One LLM client: `jimmy/llm.py`.** Nothing in `ambient/` may import an HTTP
   library or construct an `LLM`. `test_only_one_llm_client` scans the source.
   It has two endpoints: the cloud (NVIDIA) for chat, and local Ollama
   (`local_llm()`) for card decisions (D20).
8. **Captured text is untrusted data.** It reaches the model only inside
   `<context>`, below a rule telling it to ignore instructions found there. A web
   page saying "ignore previous instructions" is exactly what gets captured. This
   matters most once Stage 3 gives Jimmy actions.
9. **A model never writes a card.** It answers typed questions; `jimmy/cards.py`
   composes the line from words that exist in the evidence and real timestamps.

---

## Verified environment — don't re-probe this

Measured on this machine. Trust these numbers; re-measure only if hardware changes.

- **Hardware:** Ryzen 7 7840HS, RTX 4050 Laptop **6141 MiB VRAM**, CUDA 12.4.
- **Python:** venv is 3.12.10 at `.venv\`. System default is 3.14 and the ML stack
  does not build there.
- **DXGI pull capture** (`windows_capture.DxgiDuplicationSession`): 1920×1080 BGRA
  in ~7–14 ms. The method is `acquire_frame(timeout_ms)`, **not** `capture()`.
- **UI Automation:** a live Electron window walks **317 nodes / ~4.8k chars in
  ~230 ms**; a busier one hit **655 nodes / ~11.7k chars** and stopped at the
  0.6 s budget. The **time budget binds before the 1200-node cap** — raise
  `UIA_BUDGET_S` first if windows start losing text that matters. `.Name` costs
  ~0.2 ms/node; the expensive part is `ControlFromHandle`.
- **Chromium accessibility is off until asked.** Cold, an Electron window exposes
  **24 nodes**; woken, **317**. `screen.wake_accessibility()` sends the
  `WM_GETOBJECT`/`OBJID_CLIENT` signal once per window. Without it, UIA text is
  worthless for browsers and Electron — which is most of the screen.
- **Whisper** `distil-small.en` int8 on CUDA: **347 MiB VRAM**, 5 s of audio in
  0.08 s (~60× realtime). Nowhere near the 6 GB ceiling.
- **Tesseract binary is NOT installed.** OCR degrades to inert. UIA covers normal
  apps; canvas-rendered apps and video are currently lost. See `SCOPE.md`.
- **Storage, first real hour (old dhash gate):** 2.0 MB/h, ~26 KB/thumbnail,
  96 % of ticks skipped. **The D18 gate captures more, so re-measure**; 2.0 MB/h
  is a floor, not the new rate. The text DB is negligible beside the images.
- **Change gate (D18):** grey 160×90, capture at ≥ 0.25 % of pixels moved by
  > 12 levels. One-message chat scroll = 2–15 % on real screens, cursor blink =
  0.01 %. The old 64-bit dhash missed 7 of 8 one-message scrolls.
- **Mic:** the default input is "Headset Microphone (Realtek)". It works (peak
  9,678 when spoken into), but a quiet room reads as near-zero because noise
  suppression gates it. **Near-silence doesn't mean a dead mic.** Test by speaking
  during `ambient doctor`. The laptop mic is "Microphone Array (AMD)"; choose it
  with `MIC_DEVICE` in `ambient/config.py`.
- **Storage with the D18 gate:** 25.8 MB/h (~6.2 GB/month at 8 h/day), ~49 % of
  ticks skipped. Replay of 1.18 h real history: 5 candidates → 2 cards (D19).
- **Whisper is `large-v3-turbo`** (multilingual, auto-detect): ~1 GB VRAM, 4 s of
  audio in 0.6 s. Real Hindi accuracy is unverified (D19).
- **Ollama 0.32.13 is installed** with qwen2.5:3b / 7b / 14b. **qwen2.5:3b decides
  cards** (D20): ~1 s per question, 3.3 GB VRAM, ~10 s cold load (idle unload
  after ~5 min). 7B was slower and worse; 14B doesn't fit in VRAM.
- **bge-m3 (Ollama)**: 1024-d vectors; warm load 5.8 s; 32 chunks ≈ 4 s; ~2.5 min
  of indexing per captured hour. Needs its own long timeout: first use loads 1.2 GB.
- **NVIDIA endpoint** `https://integrate.api.nvidia.com/v1` lists its models
  **without a key**, but **listed ≠ usable by this account**: several listed
  models return 404 "not found for account" or never answer. Only a round trip
  proves a model works.
- **Default model `nvidia/nemotron-3-super-120b-a12b`, thinking off (D17):**
  **~0.8–1.1 s to first word, ~1.4 s full answer**, clean output. Thinking on:
  ~2.5 s, same answers. `nemotron-3.5-lightning` (the first pick) took **159 s**
  and leaked its reasoning as plain text. Don't switch models without measuring.
- **The hosted model sometimes returns 200 with an empty answer** (1 in 5 in the
  benchmark), and on 2026-09-25 came in runs. `LLM` makes 3 attempts, then raises.

---

## Traps that already cost time

- `pip uninstall opencv-python` **breaks `cv2`** even when `opencv-contrib-python`
  is still installed — they share one directory. Reinstall contrib with
  `--force-reinstall --no-deps` to recover.
- Do not pass f-strings to `python -c` through PowerShell. Quoting mangles them.
  Write a file to the scratchpad and run that.
- Whisper **invents text from silence** — it decoded silence as `"you"` and white
  noise as `"Thanks."` here. `audio.py` filters on RMS, `no_speech_prob`,
  `avg_logprob` and a hallucination blocklist. Do not loosen without recordings.
- Blurring that *looks* strong can still be re-detected. Test against the
  detector and after the JPEG round-trip, never by eye.
- **Never edit these docs with PowerShell `Get-Content`/`Set-Content`.** Windows
  PowerShell 5.1 reads UTF-8 as ANSI and writes back mojibake (`—` becomes `â€”`).
  Use the Edit tool, or Python with `encoding="utf-8"`.
- **Chat history leaks into answers.** An earlier answer about VS Code made a later
  time-scoped answer list VS Code for a window where it wasn't captured. The
  prompt now forbids facts from earlier turns. When testing recall, use a fresh
  `--session` per question, or you're testing the history, not retrieval.
- **A change gate can look fine and miss text.** Test gates against a
  one-message chat scroll on a dark theme, not against random noise.
- **With thinking on, the model writes its reasoning into the reply text**, before
  the JSON. `cards.parse` takes the last JSON object; don't lower `CARD_MAX_TOKENS`.
- **The mic hears the room, not just the user.** Videos and calls through the
  speakers get transcribed. Never attribute "heard near mic" speech to the user.
- **Screen furniture looks like content.** Sidebars, friend lists, your own name
  and buttons repeat across windows and produced every false RECALL. Lines seen
  in ≥ 3 capture windows are ignored (D22). RECALL also needs a ≥ 2 h gap and a
  cloud second opinion.
- **`npm install` may skip Electron's binary download.** If
  `overlay/node_modules/electron/dist/electron.exe` is missing, run
  `node node_modules/electron/install.js` in `overlay/`.
- **Never write `useEffect(() => expr)`. Always use braces.** In this Chromium,
  `scrollIntoView()` returns a Promise. Returned from an effect, React called it
  as a cleanup and the whole overlay went blank (D26). A test now scans
  `overlay/src` for this.
- **Electron's console only reaches the terminal when piped.** `bus._start_overlay`
  pipes and relays it; page errors are logged via `console-message`. To debug a
  blank overlay, build unminified (`npx vite build --minify false`) to get real
  error names.
- **Motion exit animations need direct children.** A card wrapped in a plain
  `div` inside `AnimatePresence` vanishes instantly instead of sliding out.
- **Commands to Jimmy are not captured speech.** "Jimmy, …" is stored as
  `source = 'command'` and excluded from search, speech and indexing. Otherwise a
  question answers itself (D27).
- **Screen answers must not see the chat history.** The screen changes; with thin
  evidence the model repeated the previous screen's answer verbatim (D29).
- **A capture window spans an app, not a page.** For "this page", filter by the
  current title (`Store.window_content(window_id, title)`).
- **Jimmy must never capture itself.** With its timeline open, capture re-recorded
  old text from Jimmy's own window and search ranked the copy first (D25).
  `redact.is_own_window` excludes electron.exe windows titled "Jimmy…"; keep new
  windows' titles starting with "Jimmy".
- **Never use `hash()` in a test fixture.** It's randomised per run, and a hashed
  fake embedding collided ("mckinsey" with a word in a Google ADK line). Use a
  vocabulary dict.
- **Freeze an eval set before judging it.** A script that regenerated the pool
  on each run silently mismatched the labels (D22). Keep labelled sets read-only
  in their own folder.
- **Small models copy prompt examples and invent details.** qwen2.5:7b answered
  five candidates with the prompt's example line, then made up "three years
  ago". Never put concrete example outputs in a prompt; ask one yes/no question
  per call; let code write anything the user sees (D20).
- **Escaping in shell heredocs mangles backslashes** (`\t` became a tab). Edit
  docs with Windows paths using the Edit tool, not a heredoc'd script.
- Our own recording process shows up in Windows' mic-in-use registry. Anything
  asking "is someone else on the mic" must skip `sys.executable` /
  `sys._base_executable`, as `audio.other_app_using_mic` does.
