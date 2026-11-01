# Plan, 2026-11-01: Jimmy for any Windows PC — a setup.exe, onboarding, and control over storage

The human's request: a setup **.exe** that installs Jimmy on other Windows PCs that don't have
this PC's developer tools; an onboarding as polished as professional software, in Jimmy's
own design (a logo and animation welcome); the user in control of cache, RAM and storage;
**not tied to C:** — whatever must be on C: is named in the setup, everything else goes to
the drive the user picks; tested on an independent system. Built as D60–D62.

---

## 0 · What this PC has that another PC won't (measured)

| This PC | Another PC | So |
|---|---|---|
| Python 3.12 venv, `pip install` done | nothing | Jimmy brings its own Python (`uv` installs a managed 3.12 into Jimmy's folder) |
| Node + `npm run build` | nothing | the overlay ships built, inside the app |
| CUDA Toolkit 12.4 (cuBLAS for Whisper on the GPU, a 3 GB developer install) | maybe an NVIDIA GPU, never the toolkit | GPU PCs get `nvidia-cublas-cu12` (pip, ~400 MB); cuDNN already ships inside the `ctranslate2` wheel |
| Visual C++ runtime 14.51 in System32 | often older (onnxruntime needs ≥ 14.40) or missing | the runtime DLLs are carried app-locally next to Jimmy's Python: no admin, nothing on C: |
| Ollama + qwen2.5:3b + bge-m3 | nothing | optional ("Full"); Ollama's standalone zip in Jimmy's folder, models on the data drive |
| Whisper weights in the HF cache on C: | nothing | downloaded in onboarding to the data drive (`HF_HOME`) |
| keys in `.env` / the registry, plain text | nothing | entered in onboarding, stored DPAPI-encrypted in the data folder |

## 1 · Research (2026-11-01)

- **Installer:** electron-builder's NSIS target, assisted mode (`oneClick: false`),
  **per-user** (`perMachine: false`: no admin, no UAC), `allowToChangeInstallationDirectory`,
  custom include script for the uninstaller's "keep my data?" ([NSIS options](https://www.electron.build/configuration/nsis)).
- **Python on first run:** ComfyUI Desktop's pattern: the app ships `uv`, and on first run
  `uv` installs a managed Python and the locked packages ([Comfy-Org/desktop](https://github.com/Comfy-Org/desktop)).
  Locked with hashes (`uv pip compile --generate-hashes`, installed with `--require-hashes`).
  ComfyUI's own failures came from long user-folder paths: keep Jimmy's paths short.
- **CUDA on Windows:** cuBLAS/cuDNN from pip land in `site-packages/nvidia/*/bin`, which Windows
  never searches; register them (`os.add_dll_directory` *and* `PATH`) before `ctranslate2`
  loads ([faster-whisper](https://github.com/systran/faster-whisper), [backtalk #28](https://github.com/jaredrhod/backtalk/issues/28)).
- **"DLL load failed" on clean PCs:** onnxruntime needs a recent `msvcp140.dll` (≥ 14.40);
  an old System32 copy breaks it and updating it needs admin
  ([traffic-analysis-workbench #12](https://github.com/liorongoi/traffic-analysis-workbench/pull/12)).
  App-local copies next to the interpreter avoid both.
- **Ollama:** an official standalone `ollama-windows-amd64.zip` runs `ollama serve` without the
  installer; `OLLAMA_MODELS` moves the models ([Ollama on Windows](https://docs.ollama.com/windows)).
- **Mic and camera:** Windows' "Let desktop apps access your microphone/camera" switches live in
  `HKCU\…\CapabilityAccessManager\ConsentStore\{microphone,webcam}\NonPackaged` (`Value`
  Allow/Deny). Onboarding *reads* them and opens the right Settings page; it never edits them.
- **Signing:** an unsigned setup.exe gets SmartScreen's "Windows protected your PC". Azure
  Artifact Signing ($9.99/mo) takes individuals only in the USA and Canada; elsewhere an OV
  certificate (~$150–300/yr), and even signed apps build reputation over time
  ([Microsoft](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)).
  Built unsigned now, with the signing hook ready; the onboarding and README say what the
  warning is and how to check the SHA-256 we publish.

## 2 · What goes where

| Where | What | Why it must be there |
|---|---|---|
| **C:** (always, small) | `%APPDATA%\Jimmy\location.json` (~200 bytes: where your data is) | Jimmy needs one fixed place to find your data folder |
| **C:** | Start menu and desktop shortcuts, the uninstall entry, the "start with Windows" entry (HKCU) | Windows keeps these per user on C: |
| **Your drive** (chosen in setup) | Jimmy itself (~350 MB) | |
| **Your drive** (chosen in onboarding) | Python runtime and packages (0.6–2 GB), models (0.5–5 GB), captures, thumbnails, logs, caches, Electron's own cache | |

No admin rights, no UAC prompt, nothing in System32.

## 3 · The user in control (Settings → Storage & performance)

- **Where:** the data folder, with "Move" (copies, verifies, switches the pointer).
- **How much:** keep captures for N days (default 30); a storage cap in GB (default 20): the
  oldest days go first, never the last day. Live usage: captures, thumbnails, models,
  runtime, caches, logs.
- **Cache:** clear downloads cache, logs, thumbnails older than N days, the meaning-search index.
- **RAM / GPU — a profile:** *Lite* (Whisper `small` on CPU, no local AI, webcam off: ~1.5 GB
  RAM), *Balanced* (`large-v3-turbo` on the GPU if there is one, local AI off), *Full*
  (+ Ollama cards model and meaning search, webcam curtain); plus "free GPU memory when I'm
  away" (D53) and "start with Windows".

## 4 · Onboarding (Jimmy's design: neutral-950 surfaces, sky accents, the pill, spring motion)

1. **Hello** — the animated Jimmy mark (the pill with its listening bars), one line.
2. **Your PC** — checks with ticks, live: Windows version (10 22H2+/11, x64), RAM, free space,
   GPU (NVIDIA → GPU; else CPU), mic, camera, Windows' mic/camera switches. Nothing blocks
   unless it truly can't run (32-bit or ARM Windows).
3. **Where** — the data folder on any drive, with the space each profile needs, and what stays on C:.
4. **How much** — Lite / Balanced / Full (recommended from step 2), retention and cap.
5. **Brain** — Gemini (free) and/or NVIDIA keys, or offline; test button; stored encrypted.
6. **Privacy** — what Jimmy captures, what never leaves, the exclusion list, the curtain.
7. **Installing** — the runtime, packages, models: one progress line per piece, sizes, retry.
8. **Say hi** — "Say *Jimmy*" with the live listening bars; start with Windows; done.

## 5 · Security

Per-user install, no admin. Every download over HTTPS and pinned: packages by hash
(`--require-hashes`), `uv` and Ollama by SHA-256, Whisper by Hugging Face revision. Keys
DPAPI-encrypted (only this Windows user can read them). The uninstaller removes the app,
the shortcuts and the registry entries, and asks before deleting your data. No telemetry.

## 6 · Testing on an independent system

This PC is Windows 11 Home: no Windows Sandbox, no Hyper-V. The independent system is a
**fresh GitHub Actions Windows VM** (a new machine per run): build the installer, install it
silently to `D:`, provision the *Lite* profile with the system Python, Node and CUDA kept off
`PATH`, then import every native module, run `doctor`, start the backend and its API, check
that the C++ runtime loaded from Jimmy's own folder, uninstall, and check what's left on C:.
Locally, the same on a `subst` drive. Then the human tries it on a second PC.

## Order

1. Python side: data-folder pointer, settings overrides, storage manager, DPAPI keys, CUDA DLL
   dirs, `ambient setup` (checks + model downloads as JSON lines).
2. The Electron app: launcher, onboarding, Settings tab, logo; electron-builder + NSIS.
3. Lock files; the provisioner (`uv`, app-local C++ runtime, Ollama optional).
4. Local install test; GitHub Actions on a fresh VM; docs (D60–D62).
