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

**Current state: Stages 1 and 2 are built and passing, and Stage 2's live acceptance
is met** (real key, real captures, 2026-09-22). The Jimmy core
(the one LLM client, memory, the plugin seam) lives in `jimmy/`, and the ambient
layer is its first plugin (D14, D16). Stages 3–5 are not started. See `TIMELINE.md`.

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
.\.venv\Scripts\python.exe tests\test_stage1.py       # 13 checks, no framework

.\.venv\Scripts\python.exe -m jimmy doctor           # key, model, endpoint, data
.\.venv\Scripts\python.exe -m jimmy chat             # talk to Jimmy (/context, /remember)
.\.venv\Scripts\python.exe -m jimmy ask "what was I reading yesterday?"
.\.venv\Scripts\python.exe -m jimmy remember "standup is at 10:30"
.\.venv\Scripts\python.exe tests\test_stage2.py       # 13 checks, mocked network
```

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
| `ambient/screen.py` | DXGI capture, dhash gate, UIA text, OCR fallback, thumbnails. |
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
| `tests/test_stage2.py` | stage 2 check. The real client runs against `httpx.MockTransport`. |
| `models/` | YuNet + SFace ONNX. Committed deliberately; small and pinned. |
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
8. **Captured text is untrusted data.** It reaches the model only inside
   `<context>`, below a rule telling it to ignore instructions found there. A web
   page saying "ignore previous instructions" is exactly what gets captured. This
   matters most once Stage 3 gives Jimmy actions.

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
- **Storage:** ~27 KB per thumbnail, ~16 MB/hour, ~130 MB per 8-hour day.
  The text DB is negligible beside it.
- **Dedup gate earns its keep:** a typical minute skips ~65 % of ticks as
  perceptually unchanged.
- **NVIDIA endpoint** `https://integrate.api.nvidia.com/v1` lists its models
  **without a key**, but **listed ≠ usable by this account**: several listed
  models return 404 "not found for account" or never answer. Only a round trip
  proves a model works.
- **Default model `nvidia/nemotron-3-super-120b-a12b`, thinking off (D17):**
  **~0.8–1.1 s to first word, ~1.4 s full answer**, clean output. Thinking on:
  ~2.5 s, same answers. `nemotron-3.5-lightning` (the first pick) took **159 s**
  and leaked its reasoning as plain text. Don't switch models without measuring.
- **The hosted model sometimes returns 200 with an empty answer** (1 in 5 in the
  benchmark). `LLM` retries once, then raises.

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
- Our own recording process shows up in Windows' mic-in-use registry. Anything
  asking "is someone else on the mic" must skip `sys.executable` /
  `sys._base_executable`, as `audio.other_app_using_mic` does.
