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
every decision (`python -m jimmy trace`). 95 % on the 130 real commands (was 71 %).** D43/D44: model
fallbacks, OpenAI as a second provider. **D45: the fixes from the live session of 2026-10-05**
(per-request traces, windows from speech start, slow-step fallback and "stop", plans that go on,
window tools, the console kept in `data/logs/jimmy.log`). **D47–D52: the research roadmap
built** (`docs/RESEARCH-AGENT-2026-10.md`): a lighter footprint (efficiency mode, load awareness,
a slower idle tick, cached UI Automation), fewer tools per step, every action checked, whole-task
evals, a policy layer in code, a plan's actions run without a model call each; and, behind flags
that stay off until measured on the laptop, Silero VAD, a wake word while paused, a still webcam,
a GPU budget, recipes, Windows OCR, a local fallback, OTel traces, MCP recall, a turn detector,
Kokoro, int8 vectors and small thumbnails (D53 measured them: the GPU budget and bge-m3 on the CPU
are on). **D54–D57 (`docs/PLAN-2026-10-31.md`): Gemini 3.8 Flash on the free tier with an NVIDIA
backup that can't run out; ask only when unsure (the human's amendment of non-negotiable 1);
Intelligent UI (fixed answer templates: steps, choice, confirm, list, table, checklist, chart);
plans played back live.** **D60–D62 (`docs/PLAN-2026-11-01-installer.md`): `Jimmy-Setup.exe`** —
a per-user installer for any Windows 10/11 x64 PC (no admin, any drive), an onboarding in Jimmy's
design that installs Jimmy's own Python and models into the data folder the user picks, Settings
for storage/limits/profile, and Jimmy's mark. "Jimmy, …" → an
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
.\.venv\Scripts\python.exe tests\run_all.py           # D68: every offline suite, in parallel; CI gates releases on it
.\.venv\Scripts\python.exe tests\test_stage1.py       # 15 checks, no framework

.\.venv\Scripts\python.exe -m jimmy doctor           # key, model, endpoint, data
.\.venv\Scripts\python.exe -m jimmy chat             # talk to Jimmy (/context, /remember)
.\.venv\Scripts\python.exe -m jimmy ask "what was I reading yesterday?"
.\.venv\Scripts\python.exe -m jimmy remember "standup is at 10:30"
.\.venv\Scripts\python.exe tests\test_stage2.py       # 17 checks, mocked network

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
.\node_modules\electron\dist\electron.exe . --demo --demo-ui table --snapshot shot.png   # D56: one template on invented data
.\node_modules\electron\dist\electron.exe . --demo --demo-ui dock --snapshot shot.png    # D66: the status dock
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
.\.venv\Scripts\python.exe tests\test_stage11.py  # 10 checks: the agent loop, plan/risky approval, typing guard, trace, calls, wiki, failure mid-task
.\.venv\Scripts\python.exe tests\test_stage12.py  # 28 checks: the 2026-10-05 session's misses (D45), one per report item; D46 pause
.\.venv\Scripts\python.exe tests\test_stage13.py  # 24 checks: D47–D52 (footprint, tool retrieval, checks, policy, speculation, flags)
.\.venv\Scripts\python.exe tests\test_stage14.py  # 16 checks: D54/D58 Gemini + backup chain, D55 ask when unsure, D56 templates, D57 steps
.\.venv\Scripts\python.exe -m ambient.ui         # self-check of the template validator (D56)
.\.venv\Scripts\python.exe tests\test_stage15.py  # 6 checks: D60-D61 data folder/pointer, settings, DPAPI keys, storage limits, Settings API, setup pieces
.\.venv\Scripts\python.exe tests\test_stage16.py  # 5 checks: D63 camera "in use" by gone apps / Jimmy itself, D64 updates
.\.venv\Scripts\python.exe tests\test_stage17.py  # 8 checks: D65 camera self-repair, hidden consoles, overlay/startup
.\.venv\Scripts\python.exe -m ambient.selfcheck   # D65: the camera checks, read-only, on this PC
.\.venv\Scripts\python.exe tests\test_stage18.py  # 4 checks: D66 the status dock's vitals and wiring
.\.venv\Scripts\python.exe tests\test_stage19.py  # 6 checks: D67 camera switch order, API fallback, quit, report, MCP
.\.venv\Scripts\python.exe -m ambient.report --open   # D67: a diagnostic report in data\reports (--claude: Claude Desktop's config)
.\.venv\Scripts\python.exe installer\build.py     # D61: installer\out\Jimmy-Setup-<v>.exe (+ .sha256); needs Node + internet
.\.venv\Scripts\python.exe installer\art.py       # D62: the icon and the installer's images from Jimmy's mark
.\.venv\Scripts\python.exe tests\test_commands.py # the command matrix: 177 utterances, talk, a drill
.\.venv\Scripts\python.exe tests\eval_trajectory.py  # live: 8 whole tasks on invented screens (success, calls, tokens)
.\.venv\Scripts\python.exe tests\eval_agent.py    # live: 130 real commands through rules + agent (95 %); --system d41 = 71 %
.\.venv\Scripts\python.exe -m jimmy trace -n 20   # the decision log: heard, how, route, steps, said
.\.venv\Scripts\python.exe -m jimmy wiki --build  # the user wiki (OKF) in data/okf; without --build prints its index
.\.venv\Scripts\python.exe -m jimmy mcp          # D51: read-only MCP server on stdio (one tool: recall)
.\.venv\Scripts\python.exe -m ambient forget "1 to 15 September"   # shows what goes, asks first
.\.venv\Scripts\python.exe -m ambient compact      # VACUUM + FTS optimize (also runs while you're away)
.\.venv\Scripts\python.exe tests\eval_tools.py    # live: the model's tool pick (59 cases, with sample lists; needs the key)
.\.venv\Scripts\python.exe tests\equiv_db.py snap before   # then change code, snap after, diff
```

Only one `ambient run` at a time (D35): a second one exits with a message.

**The installed app (D61).** `Jimmy.exe` (Start menu) is the launcher: the onboarding the first
time, then it updates packages if the lock changed and starts `pythonw -m ambient run` from
`<data>\runtime\venv`, which starts `Jimmy.exe` again as the overlay (`JIMMY_OVERLAY_EXE`).
Flags: `--onboarding` (again), `--provision --data D --profile lite|balanced|full [--gpu 0|1]
[--local-ai 0|1] --log F` and `--self-test --log F` (headless, for the clean-machine test),
`--onboarding --shot x.png --step N` (render a step). Test an install locally on a `subst`
drive with PATH cut to Windows' folders and `CUDA_PATH` removed; `installer/dev-install` is the
dev launcher's stand-in install folder.
`ambient run` keeps its console in `data/logs/jimmy.log` (D45: 5 × 2 MB, rotating), with quoted
text, card lines and the gate's reasons cut to their length and key-shaped strings scrubbed.

Timeline window: pill → **Timeline**, or **Ctrl+Alt+T**; its Insights tab: **Ctrl+Alt+I**
(`electron . --timeline --insights --snapshot shot.png` renders it). Snapshot it on real data
by serving the API (see `tests/test_stage5.py` for the hooks) and running
`electron . --timeline --snapshot shot.png`.

Without `NVIDIA_API_KEY`, Jimmy runs **offline**: every answer shows what retrieval
found instead of a model reply. That is intended, not a bug. The key is read from
the process environment, *or* `HKCU\Environment` (so a fresh `setx` works without
restarting anything), *or* `.env` at the repo root (D44; git-ignored, loaded by
`jimmy/config.py`). Never read, print or ask for the key's value, and never `cat` `.env`.

`JIMMY_PROVIDER=openai` (env or `.env`) switches the cloud to OpenAI: `OPENAI_API_KEY`,
`gpt-6-luna` for chat, tools and vision, `reasoning_effort` instead of NVIDIA's template
switch (D44). `JIMMY_PROVIDER=gemini` (D54): `GEMINI_API_KEY` (or `GOOGLE_API_KEY`),
`gemini-3.8-flash` for chat and tools, NVIDIA as its backup (needs `NVIDIA_API_KEY` too),
screenshots to NVIDIA unless `JIMMY_GEMINI_SCREENSHOTS=1`. Default is `nvidia`. Tests must
pass under all three: run stage 2 and 10–14 with each `JIMMY_PROVIDER` after touching
`jimmy/llm.py` or `jimmy/config.py`.

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
| `ambient/act.py` | D41: the virtual cursor's hands: UI Automation controls of the window in front, name matching, `perform` / `press` (Invoke/Toggle/Select/Expand/SetValue; D45 SetFocus for a box with only Value) after a yes; opening apps by Start-menu shortcut; D45 `top_windows`, `pick_window`, `focus_window`, `window_state`, `SHELL_CLASSES`. |
| `overlay/src/Memory.jsx` | D41: the Memory tab: reminders, goals, memories; edit, done, delete, select. |
| `tests/test_stage10.py` | D41 check: lists by voice through the tool pick, reminder ask-back, heard feedback, cursor offer/yes, Memory API, vision fallback. |
| `ambient/agent.py` | D42: the agent. Context (`<you>`, `<lists>`, `<status>`, `<open>`, `<rejected>`, `<screen>`, `<conversation>`: stable first, D47), 54 native tools (D48: `CORE` + `GROUPS` by `select_tools`, `more_tools`), the loop, plan/risky approval, code guards (`name_check`, `said_by_user`; D45 `name_fits`, CAPTCHA, identify-people, `clean_tool_name`), the timed step with fallbacks (D45; D51 local), `_verify` (D48 ✓/✗), `_speculate` (D49), recipes (D51), `first_decision` for the eval. |
| `ambient/policy.py` | D49: what the agent may do, decided in code: `check()` → refuse / stop / ask / allow for every proposed screen action. |
| `ambient/power.py` | D47: efficiency mode (EcoQoS) for background threads, battery, CPU busy, user idle. No-ops off Windows. |
| `ambient/ui.py` | D56: Intelligent UI, the Python side: `validate` (the trust boundary: known templates, capped sizes, text only), builders for code's cards, `REPLY_UI` (the model's `ui` argument). |
| `overlay/src/Templates.jsx` | D56/D57: the cards (Steps, Choice, Confirm, List, Table, Checklist, Chart) and the live `StepsFloat`; every button says words through "ask". |
| `tests/test_stage14.py` | D54–D57 check: Gemini's request and signatures, the backup, sure/unsure, "which one?", plans that start on their own, cards through the Asker. |
| `docs/PLAN-2026-10-31.md` | the research and plan behind D54–D57 (Gemini's free tier and its limits; Intelligent UI). |
| `jimmy/install.py` | D60: an installed copy: the "installed" marker, the data-folder pointer, `settings.json`, DPAPI-encrypted keys, caches off C:, CUDA DLL folders from pip. Stdlib only; imported first. |
| `ambient/storage.py` | D60: what Jimmy uses per part, the user's retention and size cap (whole old days, never today), clearing caches. |
| `ambient/setup.py` | D61: what the onboarding asks of Jimmy's Python: `verify` (every native import, where the C++ runtime loaded from), `models` (Whisper download with progress), `keys`/`settings` (on stdin). JSON lines. |
| `installer/` | D61/D62: `build.py` (uv, hash-locked requirements, staged code, app-local C++ runtime, electron-builder), `art.py` (icon and NSIS images). `stage/`, `out/`, `cache/`, `dev-install/` are build outputs, git-ignored. |
| `overlay/launcher.cjs` | D61: the installed Jimmy.exe's launcher, the onboarding's main process, the provisioner (uv, packages, models, Ollama), headless `--provision`/`--self-test`. |
| `overlay/setup-preload.cjs` | D61: the onboarding page's only bridge. |
| `overlay/updater.cjs` | D64: updates from GitHub Releases: check, download + SHA-256, `pending`, `apply` (stop Python, the setup `/S --jimmy-restart`). `node overlay/updater.cjs` self-checks. |
| `tests/test_stage16.py` | D63–D64 check: camera holders that are gone or Jimmy itself, the pending update, the off switch, what ships. |
| `ambient/selfcheck.py` | D65: self-diagnosis and self-repair of the camera (setting, Windows privacy, other apps, pictures; repairs without a restart). Agent tools `diagnose` / `fix_problem`. `python -m ambient.selfcheck` reads only. |
| `tests/test_stage17.py` | D65 check: the camera's repairs, the tools the agent finds, hidden consoles, the overlay and launcher changes. |
| `overlay/src/Dock.jsx` | D66: the status dock (listening, camera, load, update, capture, brain) and the pill's live signals; fed by `vitals` (Python, every 2 s, plus the overlay's own load from main) and `update` (main). |
| `tests/test_stage18.py` | D66 check: vitals, process usage, "show status" by voice, the dock's wiring. |
| `ambient/report.py` | D67: the diagnostic report (facts, no captures, user masked), the prefilled GitHub issue, `status.json`, the Claude Desktop config (`--claude`). |
| `tests/test_stage19.py` | D67 check: the OpenCV switch before cv2 loads, the camera API fallback, Quit, the report, the MCP tool. |
| `overlay/src/Onboarding.jsx` | D61/D62: the first run, eight steps, in Jimmy's design. |
| `overlay/src/Logo.jsx` | D62: Jimmy's mark, animated (the pill and its listening bars). |
| `overlay/src/Settings.jsx` | D60: Settings → storage, limits, profile, clean-up, start with Windows (the timeline window's 4th tab). |
| `overlay/build/` | D61: `installer.nsh` (welcome text, what stays on C:, update-safe uninstall), the icon and NSIS images. |
| `.github/workflows/installer.yml` | D61: builds the setup on a fresh Windows VM and tests it on another (install to D:, setup, self-test, update, C: footprint, uninstall). |
| `tests/test_stage15.py` | D60–D61 check. |
| `ambient/logs.py` | D45: tees `ambient run`'s console into `data/logs/jimmy.log`, rotating, with captured text cut to lengths (`redact`). |
| `jimmy/wiki.py` | D42: the user wiki in Open Knowledge Format: code pages (goals, memories, reminders, habits), model pages (projects, people, interests), index, verify. `data/okf/`. |
| `tests/test_stage11.py` | D42 check: the agent with a scripted model, through the Asker, traces, calls by name, the wiki. |
| `tests/test_stage12.py` | D45 check: each miss from the 2026-10-05 session (P0-1 … P2-10 in the report), scripted models, faked UIA and windows. |
| `tests/test_stage13.py` | D47–D52 check: cached controls vs the walk, the idle tick, tool retrieval, ✓/✗ checks, the policy, speculation, every flagged item with fakes. |
| `tests/eval_trajectory.py` | D48: live, whole tasks on `tests/eval/trajectories.json` (invented screens that change per action), scored on success, calls, tokens, seconds. |
| `jimmy/otel.py` | D51: traces as OpenTelemetry GenAI spans (OTLP JSON) to `data/logs/otel.jsonl`, with `JIMMY_OTEL=1`. Names and timings only. |
| `jimmy/mcp.py` | D51: `python -m jimmy mcp`, a stdio MCP server with one read-only tool, `recall` (6,000-char cap, marked as data). |
| `tests/eval/` | D42: frozen real commands (`real_commands.json`) and invented screens (`screens.json`); D48 `trajectories.json`. Don't edit labels; add new files. |
| `tests/eval_agent.py` | D42: live, the first decision on the frozen set: `--system agent` (rules + agent) or `d41` (the baseline). |
| `tests/equiv_db.py` | D38: before/after equivalence of 43 read paths on a frozen copy of the real DB. Use it for any change to db/recall/insights/gate. |
| `overlay/src/main.jsx` | picks the page by hash: the overlay, or `#timeline` / `#insights`; reduced motion respected. |
| `overlay/src/index.css` | the transparent sheet, and the transform-only keyframes (equalizer, shimmer, progress). |
| `tests/test_commands.py` | D37: the command matrix (177 utterances, 18 talk negatives, a 25-command drill). Add rows for real misses. |
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
| `docs/RESEARCH-AGENT-2026-10.md` | research and a measured roadmap for the agent, voice and footprint (2026-10-07). Built as D47–D52; the flagged items still need the measurements it names. |
| `docs/img/` | README screenshots: the real overlay and model on **invented** pages, never real captures (they hold personal data). |
| `data/` | the capture DB and blurred thumbnails. Never commit. |
| `site/` | the public website (static, in the overlay's own dark design: the pill as navigation, re-created panels, cursor and curtain; dark only), hosted on Render via `render.yaml`. `python site/check_site.py` must print `ok`: one github.com link only (the hero button). Every number on it comes from a D-record; update it when those change. Render must create it as a **Blueprint** (or a Static Site): a hand-made Python web service ignores `render.yaml` and runs `pip install -r requirements.txt` (since D59 that no longer fails, but it installs ~1 GB of desktop-app packages for nothing: still make it static). An existing Python web service that must be kept serves it with `site/serve.py` instead (Build Command `echo "no build"`, Start Command `python site/serve.py`; stdlib only, same headers as `render.yaml`, which it must stay in step with). `site/video/` holds the trailer (`trailer.mp4`, re-encoded from `C:\Code\Video-Studio-projects\jimmy-launched\out\launched-v7.2.mp4`) and short muted clips cut from it with ffmpeg, each with a poster `.jpg`; no clip uses 0:56–1:00 (third-party YouTube footage). `site/site.js` plays clips only on screen and never with reduced motion, and runs tabs, the chapter player, count-ups and the docs TOC; the CSP therefore has `script-src 'self'` and `media-src 'self'`. Its screenshots in `site/img/` are copies of `docs/img/`; `*.png` is git-ignored, so new site images need a `!site/...` line in `.gitignore` or they never reach the deploy. |

---

## Invariants — do not break these

From `AMBIENT_LAYER.md`'s non-negotiables. Each is an *absent code path*, not a
setting that defaults to off.

1. **No action executes without explicit user approval** — amended by the human on
   2026-10-31 (D55): a reversible action Jimmy is *sure* of (`policy.sure`: the user named
   that control, nothing else fits as well) runs without a yes, shown first with a moment
   to say "stop". Anything irreversible or uncertain still asks. `AUTONOMY = "always"`
   restores the old rule.
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
12. **Jimmy acts on another app only through UI Automation patterns** (D35 scroll, D41,
   D42), after a yes, or (D55) on its own when `policy.sure` holds and `policy.check` says
   *allow*. Each action is shown by Jimmy's cursor; one yes approves a plan's steps (a plan
   naming nothing risky starts without one, D55), anything risky asks again on its own.
   No mouse events; the one key is Enter (`submit`), sent only after UI Automation
   focused that box and the focus was checked. Never in excluded windows, never into
   a password box, never text the user didn't say. D45: "click" on a box with only
   Value is UIA `SetFocus`; switching / minimizing / maximizing a window is UIA
   `SetFocus` / `WindowPattern` (one yes, never a close). Never a CAPTCHA. D49: every proposed
   action passes `ambient/policy.py` first; a plan's speculative actions only while it says *allow*.

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
- **Tesseract binary is NOT installed.** OCR degrades to inert unless `winocr` is installed
  (D51: Windows' own OCR engine, tried first). UIA covers normal
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
  after ~5 min). 7B was slower and worse; 14B doesn't fit in VRAM. Also pulled (D53):
  qwen3:4b, `qwen3-4b-8k` (a Modelfile at 8k context: 3.9 GB, 3.7 s a tool step, but 38/130
  empty answers from thinking) and `qwen3:4b-instruct-2507` (not measured yet).
- **D53, measured:** Ollama's two models hold ~3.2 GB; unloading takes 2 s, then bge-m3 is
  back in 0.4 s and the cards model in 5.3 s (65 s from a cold disk). bge-m3 on the CPU:
  0.40 s a query (GPU 0.26 s). Kokoro (`models/`, git-ignored): load 2.4 s, a 4 s sentence
  in 1.4 s on the CPU. LiveKit's turn detector (`models/turn-detector`, v0.4.1-intl): ~35 ms
  a line; its output is a small probability (cut lines ≤ 0.086, whole ≥ 0.09).
- **This laptop is often on battery**: `power.constrained()` is then true and D47 halves the
  optional loops (webcam, indexing).
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
- **Gemini free tier, 2026-11-01 (D58):** `gemini-3.8-flash` timed out or said 503 "high
  demand" on 5 of 5 calls (doctor: 107 s to a first word); 3.7-flash 503/429; 3.6-flash
  2.6–4.3 s; **3.5-flash-lite 0.6–3.8 s**; 3.1-flash-lite 1.2–5.1 s. Through Jimmy with the
  chain (3.8 → 3.5 Flash-Lite → NVIDIA, one try each, 6 s to a first word, a failed model
  resting a minute): 0.8–1.8 s to the first spoken word. Network to Google: 0.7 s.
  Evals on Gemini (all from 3.5 Flash-Lite): 130 commands **122/130**, median 1.5 s;
  8 whole tasks **8/8 in 42 s** (NVIDIA the same day: 5/8, 167 s).
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
  to a new eval file, not to the frozen one. D45: then `data/logs/jimmy.log` for what
  only the console said (errors, "not without the name", who resumed a pause).
- **Print captured text quoted (`!r`)** (D45). The console goes to `data/logs/jimmy.log`,
  and `logs.redact` cuts quoted strings to their length; captured text printed bare
  would be kept on disk outside the captures, where "forget a span" can't reach it.
- **The trace is per request thread** (D45). `Asker._trace` is a property over a
  `threading.local`; a second request used to replace a shared one mid-flight. Write to
  it only from the request's own thread (`publish` does).
- **Listening windows compare when a line *began*** (`ts_start`, D45), not when Whisper
  finished. `hear(0, …)` in a test means "now".
- **Paused means the mic hears only the name** (D46): `bus._on_audio` returns before any
  write and calls `hear(..., name_only=True)`. Anything new that reads the mic while
  paused must store nothing either.
- **Agent control numbers shift after every action** (D45): click / type / submit carry
  the name too, and a number whose control has a different name is refused. Scripted
  tests must give the id in reading order *and* the matching name.
- **httpx's read timeout is per chunk**, so it isn't a step limit: agent steps run on a
  worker thread with `STEP_TIMEOUT_S` wall-clock, then the fallback model (D45). Scripted
  models without `tool_fallback` skip the fallback.
- **Agent tool ids are in reading order** (top to bottom, then left to right), so a
  window's caption buttons come first. Tests that script ids must count them.
- **Ambient code never builds a model client, even in eval helpers** (invariant 7):
  `first_decision` takes the `llm` from its caller. `test_only_one_llm_client` also fails
  on the text `jimmy.llm` anywhere in `ambient/`: reach core helpers through `jimmy.core`
  (D50's `unload_local` is re-exported there).
- **Every screen action goes through `policy.check`** (D49). A new guard belongs there,
  not in `Agent._act`, so the plan path and speculative actions get it too.
- **A plan's `actions` run without the model** (D49): a scripted test that gives a plan
  `actions` needs fewer model steps after the yes; one without them is step by step.
- **D50–D52 knobs are off for a reason**: each has an unmeasured threshold or needs a
  package or model file. Turn one on only with the measurement its `config.py` comment
  names, and record the numbers in a new D-record.
- **Agent context order is for the prompt cache** (D47): anything per-request goes after
  `<screen>` (as `<how_it_went_before>` does), or every step misses the cache.
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
- **A test's LLM client must never reach the network** (D54). A default client gets a real
  NVIDIA backup from your real key; any `transport=` (a test) means no backup. A client
  built without one in a test, under `JIMMY_PROVIDER=gemini`, once called NVIDIA for real.
- **Gemini 3 needs its thought signatures back** (D54): pass the model's tool calls back
  exactly as received (`extra_content` included); `LLM._wire` adds Google's stand-in for a
  call Gemini didn't make and strips it for other endpoints.
- **Suites 11–13 pin `AUTONOMY = "always"`** (D55): they prove the yes-for-everything rules.
  New autonomy tests go in stage 14, which sets `AUTO_GRACE_S = STEP_SHOW_S = 0`.
- **"Search for X" is the timeline's** (a fast rule filters Jimmy's own history); a test of
  a screen search plan must say "type X in the search box and press enter".
- **On battery the webcam loop runs at half rate** (D47 `power.constrained`): a test that
  times the presence thread must pin `pres.power.constrained` (stage 9 does).
- **`requirements.txt` carries `; sys_platform == "win32"` on its Windows-only packages** (comtypes, PyAudioWPatch, uiautomation, webrtcvad-wheels, windows-capture, winocr). Without them a Linux host (Render, CI) can't `pip install -r` it: PyAudioWPatch, webrtcvad-wheels and windows-capture have no Linux wheels. `pip freeze > requirements.txt` drops the markers: put them back.
- **A dev checkout never follows `%APPDATA%\Jimmy\location.json`** (D60): only code carrying
  `jimmy-installed.json` does. Testing an install on this PC leaves that pointer behind; the
  repo's `data\` is unaffected, by design.
- **Nothing Jimmy downloads may live in the install folder** (D61): installing over an older
  version runs its uninstaller and electron-builder's update wipes `$INSTDIR`. Jimmy's Python
  is in `<data>\runtime`; the uninstaller's clean-up is inside `${ifNot} ${isUpdated}`.
- **A changed `requirements.txt` needs `installer/build.py`** to relock (hashes) and a new
  setup; installed copies update their packages at the next start (`ready.json`'s `lock`).
- **The app-local C++ runtime goes next to the base interpreter** (`<data>\runtime\python\cpython-…`),
  not the venv: a venv's python.exe launches the base one, whose folder Windows searches first.
- **Windows tools write JSON with a BOM** (PowerShell `Set-Content -Encoding utf8`); the
  launcher strips it before `JSON.parse`.
- **A release is a version bump** (D64): `overlay/package.json`'s `version` is the only one
  (`installer/build.py` reads it). Pushing a new one to `main` publishes `v<version>` after the
  clean-machine test; installed copies then update themselves. Never reuse a version.
- **The camera/mic registry lies** (D63): `LastUsedTimeStop == 0` stays for an app that crashed
  holding the device. `audio._holders` checks the process is running; keep it that way.
- **Node on Windows: `detached` PowerShell does nothing** (no console), and a non-detached child
  dies with its parent (Node's kill-on-close job). Start GUI programs detached; wait for
  PowerShell (D64's `apply`).
- **OpenCV's Media Foundation opened this webcam in 16.5 s** (D65): hardware transforms. Keep
  `OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS=0` set in `jimmy/install.py`: OpenCV reads it once,
  when it loads (D67: set in `presence.py`, it worked in a dev test and not in an installed copy).
  Open cameras only through `presence.open_camera`. A camera check in this tool's sandbox can hang.
- **Test an installed copy's code with its own environment** (D67): `JIMMY_OVERLAY_EXE` set, or the
  overlay (and with it the camera) never starts and the test proves nothing.
- **Don't rely on COM being initialised by side effect** (D65): moving the camera's start to a
  timer made the first UI Automation reads fail. `bus.run` initialises it for the capture thread.
- **Under `pythonw` every console program opens a visible window** (D65): `install.hide_consoles`
  covers Python; a Node `detached` spawn has no console either, so its console children flash.
- **Never let a file delete in the updater throw** (D66): right after an update the setup is still
  running from `<data>\cache\update`; the launcher died on a refused delete before starting Jimmy.
- **Run `tests\run_all.py`, not a hand loop** (D68): it reads exit codes and output; CI runs it
  before every build. A `print` of non-Latin text on a piped stdout used to kill its thread.
- **A test's `OverlayAPI` must be `.start()`ed and `.stop()`ped**: `server.shutdown()` on one
  that never served waits forever.
- **Ollama loads qwen3 at its full context** (256k: 37.5 GB asked, D53). A local model for
  this laptop needs a Modelfile with `num_ctx` (`qwen3-4b-8k` is one), and a thinking model
  spends its whole `max_tokens` thinking: use an instruct (non-thinking) variant.
