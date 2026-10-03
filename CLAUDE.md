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

**Current state: all five stages are done, plus voice Q&A (D25), Insights + commands (D31),
cards Jimmy writes itself (D32), hands-free UI (D33), the privacy curtain (D34), fixes from
the first real session (D35), English + Hindi only (D36), "remember my face" (D37), a
performance pass (D38), "live" (D39: a curtain that follows you, resting while away,
asking without the name, forget a span, timers), its first-session fixes (D40: calls,
eye calibration, UIA scroll, fresh timeline after a forget) and D41: every unplaced request
picked by the model with your lists in context, reminders/goals/memories by voice and in a
Memory tab, "listening…/heard" feedback, seeing the screen (vision model), and a virtual
cursor that presses or types after a yes. **D42: Jimmy is an agent** (`ambient/agent.py`):
one loop that sees its own state, the user's wiki (OKF), their lists and the window's
controls, picks native tools, runs multi-step screen tasks on one yes for a plan, and logs
every decision (`python -m jimmy trace`). 95 % on the 130 real commands (was 71 %).** "Jimmy, …" → an
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
.\.venv\Scripts\python.exe tests\test_stage2.py       # 15 checks, mocked network

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
.\.venv\Scripts\python.exe tests\test_stage6.py   # 6 checks: insights estimate, usage answers, commands, time phrases, small thumbs
.\.venv\Scripts\python.exe -m ambient.insights    # self-check for the time estimate
.\.venv\Scripts\python.exe tests\test_stage7.py   # 11 checks: nav, reminders, deadlines, offers, curtain, presence
.\.venv\Scripts\python.exe -m ambient deadlines --scan --dry   # date lines in history, no model
.\.venv\Scripts\python.exe tests\test_stage8.py   # 7 checks: the first real session's misses, tools, ask-back
.\.venv\Scripts\python.exe tests\test_face.py     # 6 checks: remember-my-face capture, template, tracker
.\.venv\Scripts\python.exe tests\test_stage9.py   # 14 checks: curtain follows you, presence thread, no-name asks, calls, calibration, forget, timers
.\.venv\Scripts\python.exe tests\test_stage10.py  # 7 checks: lists by voice, remind asks what, heard feedback, cursor, Memory tab, vision fallback
.\.venv\Scripts\python.exe tests\test_stage11.py  # 9 checks: the agent loop, plan/risky approval, typing guard, trace, calls, wiki
.\.venv\Scripts\python.exe tests\test_commands.py # the command matrix: 169 utterances, talk, a drill
.\.venv\Scripts\python.exe tests\eval_agent.py    # live: 130 real commands through rules + agent (95 %); --system d41 = 71 %
.\.venv\Scripts\python.exe -m jimmy trace -n 20   # the decision log: heard, how, route, steps, said
.\.venv\Scripts\python.exe -m jimmy wiki --build  # the user wiki (OKF) in data/okf; without --build prints its index
.\.venv\Scripts\python.exe -m ambient forget "1 to 15 September"   # shows what goes, asks first
.\.venv\Scripts\python.exe -m ambient compact      # VACUUM + FTS optimize (also runs while you're away)
.\.venv\Scripts\python.exe tests\eval_tools.py    # live: the model's tool pick (59 cases, with sample lists; needs the key)
.\.venv\Scripts\python.exe tests\equiv_db.py snap before   # then change code, snap after, diff
```

Only one `ambient run` at a time (D35): a second one exits with a message.

Timeline window: pill → **Timeline**, or **Ctrl+Alt+T**; its Insights tab: **Ctrl+Alt+I**
(`electron . --timeline --insights --snapshot shot.png` renders it). Snapshot it on real data
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
| `ambient/db.py` | SQLite + FTS5 store. Schema, writes, unified search; D39 `measure` / `forget` / `compact`. |
| `ambient/redact.py` | exclusions + the ephemeral face stage. **The sensitive file.** |
| `ambient/screen.py` | DXGI capture, 160×90 change gate, UIA text, OCR fallback, thumbnails. |
| `ambient/audio.py` | WASAPI capture, VAD chunking, Whisper + hallucination filtering. |
| `ambient/bus.py` | the one loop. Capture-window lifecycle lives here. |
| `ambient/__main__.py` | CLI: `run`, `search`, `stats`, `doctor`. |
| `ambient/plugin.py` | the ambient layer as a Jimmy plugin: time phrases → bounded search + activity; D39 `date_range` (months, day ranges) for forgetting. |
| `jimmy/config.py` | core tunables: endpoint, model, context budget. |
| `jimmy/llm.py` | **the only LLM client in the repo.** Streaming, one warm connection, `<think>` stripping. |
| `jimmy/memory.py` | Jimmy's memory (`data/jimmy.db`): remembered facts, chat turns, and the safe `fts_query`. |
| `jimmy/core.py` | `Jimmy.ask` (whole answer: `str`) and `Jimmy.ask_stream` (`Iterator[str]`): gather from memory + plugins → bounded context → LLM. The prompt lives here. |
| `jimmy/__main__.py` | CLI: `chat`, `ask`, `remember`, `doctor`. |
| `tests/test_stage1.py` | stage 1 check. Assert-based, no pytest. |
| `ambient/gate.py` | Stage 3 Tier 1: moments, RECALL/FOCUS rules, hard limits, `replay()`. No LLM. |
| `jimmy/cards.py` | Stage 3 Tier 2: typed questions to the local model (default) or cloud; code writes the ≤7-word card. |
| `ambient/ask.py` | D25/D27/D28: wake word, `route()` (chat / screen / recall / clarify / show + follow-ups), `interpret()`, evidence, `Asker` (conversation, ask-back, overlay events; D39 follow-up + eye-contact asks, timers, forget), `Voice` (SAPI). |
| `ambient/demo.py` | D28: `ambient run --demo`, scripted questions through the real Asker, for screen recordings. |
| `ambient/insights.py` | D31: where the day went: gap-capped time per app, runs, hours, week; usage answers written in code. |
| `overlay/src/Insights.jsx` | D31: the Insights tab, plus the shared chart pieces (colours, bars, day ribbon) the overlay reuses. |
| `tests/test_stage6.py` | D31 check: insights, usage answers, commands, time phrases, small thumbnails. |
| `ambient/proactive.py` | D32: RESUME / SUGGEST / REMIND / DEADLINE / RECAP cards, reminder and date parsing, `.ics` files. |
| `ambient/presence.py` | D34/D37/D39: webcam presence for the curtain: finds your face, follows where you sit (`Follow`), identity per track, resting looks while away; your gaze zone and lips as yes/no history. |
| `tests/test_stage7.py` | D32–D34 check. No webcam, no network. |
| `tests/test_stage8.py` | D35 check: the human's real misses from 2026-10-02, tool picking, ask-back. |
| `tests/test_face.py` | D37: guidance, capture steps, DPAPI template, tracker with your face. No webcam. |
| `tests/test_stage9.py` | D39: follow on drawn scenes, identity per track, the presence thread on a fake camera, eyes/lips, follow-up and eye-contact asks, timers, forget + compact, date spans, resting. |
| `ambient/act.py` | D41: the virtual cursor's hands: UI Automation controls of the window in front, name matching, `perform` (Invoke/Toggle/Select/Expand/SetValue) after a yes; opening apps by Start-menu shortcut. |
| `overlay/src/Memory.jsx` | D41: the Memory tab: reminders, goals, memories; edit, done, delete, select. |
| `tests/test_stage10.py` | D41 check: lists by voice through the tool pick, reminder ask-back, heard feedback, cursor offer/yes, Memory API, vision fallback. |
| `ambient/agent.py` | D42: the agent. Context (`<status>`, `<you>`, `<lists>`, `<screen>`), 50 native tools, the loop, plan/risky approval, code guards (`name_check`, `said_by_user`), `first_decision` for the eval. |
| `jimmy/wiki.py` | D42: the user wiki in Open Knowledge Format: code pages (goals, memories, reminders, habits), model pages (projects, people, interests), index, verify. `data/okf/`. |
| `tests/test_stage11.py` | D42 check: the agent with a scripted model, through the Asker, traces, calls by name, the wiki. |
| `tests/eval/` | D42: frozen real commands (`real_commands.json`) and invented screens (`screens.json`). Don't edit labels; add new files. |
| `tests/eval_agent.py` | D42: live, the first decision on the frozen set: `--system agent` (rules + agent) or `d41` (the baseline). |
| `tests/equiv_db.py` | D38: before/after equivalence of 43 read paths on a frozen copy of the real DB. Use it for any change to db/recall/insights/gate. |
| `overlay/src/main.jsx` | picks the page by hash: the overlay, or `#timeline` / `#insights`; reduced motion respected. |
| `overlay/src/index.css` | the transparent sheet, and the transform-only keyframes (equalizer, shimmer, progress). |
| `tests/test_commands.py` | D37: the command matrix (131 utterances, 16 talk negatives, a 25-command drill). Add rows for real misses. |
| `tests/eval_tools.py` | live: the cloud model's tool pick on 34 English/Hindi requests. Needs the key. |
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
   The one exception (D37, the human's spec amendment): the owner's own template,
   on "remember my face", DPAPI-encrypted, written in exactly one place.
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
   D32's cards follow the same rule: `ambient/proactive.py` writes every line.
10. **The webcam recognises only its owner, and only if asked** (D34, D37, D39).
   `presence.py` finds a face and follows where it sits. After "remember my face"
   it matches a new face against the owner's DPAPI-encrypted template (per track,
   not per frame); every other face's vector lives for one comparison. For the
   owner's face only: looking-at-screen and lips-moving as yes/no values, two
   minutes, RAM (D39's spec amendment); the eye calibration stores only a few
   numbers in settings (D40). No frame is kept; nothing pickles. A test
   checks there is one write path (`self.owner.save(e.samples)`) and no image write.
11. **Jimmy proposes; you approve** (D32). Focus, page, draft, calendar event:
   each waits for your yes, and drafts/events go no further than your
   clipboard or your calendar app's own confirm.
12. **Jimmy acts on another app only through UI Automation patterns, after a yes**
   (D35 scroll, D41, D42). Each action is shown by Jimmy's cursor; one yes approves a
   plan's steps, anything risky asks again on its own, a lone action asks each time.
   No mouse events; the one key is Enter (`submit`), sent only after UI Automation
   focused that box and the focus was checked. Never in excluded windows, never into
   a password box, never text the user didn't say.

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
  **That was with 640 px thumbnails.** At 1280 px (D27) they average ~80–88 KB, so
  ~30–85 MB per active hour, ~90–250 GB a year at 8 h/day (D38).
- **Whisper is `large-v3-turbo`**, restricted to English and Hindi (D36): ~1 GB VRAM,
  4 s of audio in 0.6 s. Real Hindi accuracy is unverified (D19). Hindi requests
  are understood via one model call that also returns the English.
- **Ollama 0.32.13 is installed** with qwen2.5:3b / 7b / 14b. **qwen2.5:3b decides
  cards** (D20): ~1 s per question, 3.3 GB VRAM, ~10 s cold load (idle unload
  after ~5 min). 7B was slower and worse; 14B doesn't fit in VRAM.
- **bge-m3 (Ollama)**: 1024-d vectors; warm load 5.8 s. Via 127.0.0.1 with a kept
  connection: ~0.4–0.5 s per call (Ollama's fixed cost), 32 chunks in 1.1 s; hybrid
  search 0.5 s (D38; the old "32 chunks ≈ 4 s" included the localhost delay).
  Kept loaded 60 min (`EMBED_KEEP_ALIVE`). Needs its own long timeout: first use loads 1.2 GB.
- **OpenCV single-threaded is cheaper here** (D38): YuNet 640 px 20 ms CPU vs 65 ms on
  the default 16 threads; 1280 px 94 ms. SFace ~50 ms a face.
- **NVIDIA endpoint** `https://integrate.api.nvidia.com/v1` lists its models
  **without a key**, but **listed ≠ usable by this account**: several listed
  models return 404 "not found for account" or never answer. Only a round trip
  proves a model works.
- **Models (D43): chat `nvidia/nemotron-3-ultra-550b-a55b`, tool picks `openai/gpt-oss-20b`,**
  thinking off. D17's `nemotron-3-super-120b-a12b` reached **end of life 2026-10-03
  (HTTP 410)**. Ultra: first word 1.0–1.4 s, full answer 2.0–2.5 s, clean; but
  **HTTP 500 on 30 of 130 tool calls**, so it doesn't pick tools. gpt-oss-20b:
  120/130 real commands, median 1.4 s (terse as a chat voice). `nemotron-3.5-lightning`
  took 45–66 s and wrote garbage (in D17: 159 s). A 404/410 now moves the client to
  the next model (`MODEL_FALLBACKS`) and prints it. Don't switch models without measuring.
- **The hosted model sometimes returns 200 with an empty answer** (1 in 5 in the
  benchmark), and on 2026-09-25 came in runs. `LLM` makes 3 attempts, then raises.
  On 2026-10-03, 6 of 59 eval calls in one run.
- **Vision models usable by this key (2026-10-03, D41):** only
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (0.7–3.5 s; once 503 "request
  limit") and `meta/llama-3.2-11b-vision-instruct` (1.1–9 s). Gemma 4, Kimi K3,
  GLM-5.3, llama-3.2-90b-vision time out; phi-3-vision, gemma-3, vila, cosmos 404.
- **Native tool calls (D42, D43):** thinking **off** (on, nemotron-3-super returned
  nothing). gpt-oss-20b median 1.4 s per step (one 43 s run of empties in 130);
  nemotron-ultra 500s; glm-5.3-flash 19–36 s, deepseek-v4.1-flash and kimi-k3 time out;
  nemotron-nano-3, kimi-k2.6, mistral-large-2 404. A live 2-step task on a
  WinForms window: 8.7 s from request to done (plan, yes, type, click).
- **UI Automation controls (D41):** one `FindAll` on pattern availability: the
  Claude app, 113 actionable controls in 0.43 s. WinForms buttons and boxes take
  Invoke / SetValue; Tk windows expose nothing.

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
- **`ELECTRON_RUN_AS_NODE=1` is inherited from VS Code / Claude terminals** and makes
  the overlay's electron.exe run as plain Node (`Cannot read properties of undefined
  (reading 'whenReady')`). `bus._start_overlay` strips it; anything else that launches
  Electron must too.
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
- **Usage numbers are estimates.** Frames are change-driven, so each counts until
  the next, capped at `ACTIVE_GAP_S`. Returning to an unchanged window writes a
  "switched" row (D31); without it, time kept counting for the app you'd left.
- **Bare navigation words are live after Jimmy shows something** (D33): "next",
  "close", "scroll down" need no wake word for 45 s. Any new nav phrase must
  be a whole-phrase match; "just talking about lunch" once became a filter.
- **The curtain is drawn by the overlay window**, so a capture under it would
  store the curtain: `bus.tick` returns "curtained" before reading the screen.
- **Never point at `localhost` on Windows** (D38). It tries IPv6 first and Ollama
  listens on IPv4: ~2.4 s on every new connection. Use 127.0.0.1, and keep
  clients open (httpx closes idle ones after 5 s unless `keepalive_expiry` says otherwise).
- **`(first, *gen)` reads the whole generator** (D38): it made paged vector
  search load every page at once. Use `itertools.chain([first], gen)`.
- **Optimise against a frozen copy of the real DB, before and after.** D38's
  equivalence script compared 43 read paths; keep doing that for anything in
  `db.py` or `recall.py`.
- **`cards.parse` reads flat JSON only.** Tool picks are nested (`"args": {...}`);
  use `ask._json_obj`. The cloud model also puts `reason` beside `args`.
- **The heredoc trap bites code too**: a `\\b` in a heredoc'd Python edit became a
  backspace character inside a regex (D35). Write edit scripts to a file.
- **Read the human's real session before guessing** (D35): commands are in
  `audio_segments` with `source = 'command'`, answers in `jimmy.db` `turns`.
- **Commands and usage questions route before everything else** (`ask.route`).
  A new pattern there can swallow real questions: add its negative case to
  `test_router_commands_and_stats` first.
- **`Presence()` in a test loads the real `data/owner_face.bin`** (the owner enrolled
  on 2026-10-02), so a test expecting "no face remembered" silently gets identity
  checks. Pass `owner=` a stub (`tests/test_stage9.py` has `_Nobody`).
- **Another app holding the mic switches off asking without the name** (D9's
  "that's a call" rule). On 2026-10-02 Discord held the mic all evening and eye
  contact looked broken. Check `audio.mic_holders()` before debugging gaze; the
  user can say "I'm not on a call" (D40).
- **An unmeasured threshold must not veto.** D39's lip check rejected lines and
  then blocked eye contact for 30 s, in a loop. Signals tuned on drawings decide
  nothing until a calibration has measured them on the real camera (D40).
- **UI Automation off the main thread needs `auto.UIAutomationInitializerInThread()`**
  (the scroll runs on an API thread). `uiautomation`'s client is in
  `uiautomation.uiautomation._AutomationClient`; `TreeScope_Descendants` is 4.
- **Read the decision log first** (D42): `python -m jimmy trace` shows what Jimmy
  heard, how, which tools it called with what, and what it said. Then add the miss
  to a new eval file, not to the frozen one.
- **Agent tool ids are in reading order** (top to bottom, then left to right), so a
  window's caption buttons come first. Tests that script ids must count them.
- **Ambient code never builds a model client, even in eval helpers** (invariant 7):
  `first_decision` takes the `llm` from its caller.
- **Every unplaced request now costs one tool pick** (D41). Keep the rules for the
  fast, unambiguous phrases; the model resolves the rest with `<state>`. A failed
  pick pauses picks for 60 s (`_pick_down_until`). Re-run `tests/eval_tools.py`
  after any change to `TOOLS_Q`: a reworded line made "start watching again" and a
  Hindi "delete September" fall to "cannot".
- **A follow-up window takes statements too** (D39): a test of "this isn't a
  request" must close `followup_until` first, or it tests the follow-up.
- **The curtain's thresholds are from drawn scenes** (D39): turned head 0.55–0.69,
  empty chair 0.42, `FOLLOW_MIN` 0.5. The console prints the last match when it
  decides you left; tune from that, not from the drawings.
- Our own recording process shows up in Windows' mic-in-use registry. Anything
  asking "is someone else on the mic" must skip `sys.executable` /
  `sys._base_executable`, as `audio.other_app_using_mic` does.
