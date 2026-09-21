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

**Current state: Stage 1 (context bus) is built and passing.** Stages 2–5 are not
started. The Jimmy core (LLM client, memory/RAG, plugins) did not exist and is
built **in this repo** as part of Stage 2 (D14). See `TIMELINE.md`.

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
```

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
| `tests/test_stage1.py` | the runnable check. Assert-based, no pytest. |
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
