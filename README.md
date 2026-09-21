# Jimmy — ambient layer

An always-on desktop assistant for Windows 11, built as a subsystem of Jimmy.

> Continuous capture is commodity. The product is the gate that decides to stay
> quiet.

**Status: Stages 1 and 2 work.** It captures your screen and speech, turns them
into searchable text, and stores nothing it shouldn't. And you can ask Jimmy about
it in the terminal: "what was I reading yesterday?" There's no overlay yet, and
Jimmy doesn't interrupt you yet; that's Stage 3, the part that matters most.

| Doc | What's in it |
|---|---|
| [`AMBIENT_LAYER.md`](AMBIENT_LAYER.md) | the build spec — the authority |
| [`CLAUDE.md`](CLAUDE.md) | orientation for AI sessions; verified environment facts |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | components, threading, why each choice |
| [`DATA-FLOW.md`](DATA-FLOW.md) | the tick path, the audio path, the schema |
| [`DECISIONS-AND-WHY.md`](DECISIONS-AND-WHY.md) | the decision log, with evidence |
| [`SCOPE.md`](SCOPE.md) | what's in, what's out, what's owed |
| [`TIMELINE.md`](TIMELINE.md) | stage status and acceptance gates |

---

## Setup

Needs Windows 11, an NVIDIA GPU, and **Python 3.12** — not 3.14, whose wheels
don't exist for this stack yet.

```powershell
cd C:\Code\Jimmy
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The face models in `models/` are already committed. Whisper downloads its weights
on first run (~40 s once, then cached).

**Optional — OCR.** Without the Tesseract binary, OCR is inert and canvas-rendered
apps and video contribute no text. Normal apps are unaffected. Install it and put
it on PATH to close that gap; no code change needed.

**For Jimmy's answers — an NVIDIA API key.** Free at build.nvidia.com: sign in,
open any model, click **Get API Key** (it starts with `nvapi-`), then in your own
terminal:

```bash
setx NVIDIA_API_KEY "nvapi-your-key-here"
```

Without it, Jimmy still runs, in offline mode. Every answer shows what it
*found* in your captures and memory, which is useful on its own and is exactly
what would have been sent to the model.

---

## Using it

Start with `doctor`. It tells you what actually works on your machine rather than
what should:

```powershell
.\.venv\Scripts\python.exe -m ambient doctor
```

```
  ok    screen (dxgi)   1920x1080 bgr
  ok    uia text        Code.exe | 4784 chars from 317 nodes in 231ms
  ok    face models     models present
  FAIL  ocr             no tesseract binary; UIA-only (canvas/video lost)
  ok    whisper/cuda    cuda devices=1 compute=['int8', 'float16', ...]
  ok    audio (wasapi)  mic=Headset Microphone loopbacks=4 (capture_loopback=False)
  ok    store           C:\Code\Jimmy\data\ambient.db frames=0 text=0
```

Then capture, and search:

```powershell
.\.venv\Scripts\python.exe -m ambient run                      # until ctrl-c
.\.venv\Scripts\python.exe -m ambient run --seconds 60 --no-audio
.\.venv\Scripts\python.exe -m ambient search "trigger gate"
.\.venv\Scripts\python.exe -m ambient stats
```

One query spans what you saw and what was said:

```
Mon 21 Sep 01:37  [screen/uia]  bus.py - Jimmy
    ...the [trigger] [gate] is a cost control as much as...
Mon 21 Sep 01:41  [audio/mic]   mic
    ...tune the [trigger] [gate] before stage four...
```

Tunables all live in [`ambient/config.py`](ambient/config.py), each with its
reasoning next to it. Change knobs there, not in code.

### Talking to Jimmy

```powershell
.\.venv\Scripts\python.exe -m jimmy chat
.\.venv\Scripts\python.exe -m jimmy ask "what was I reading about sqlite yesterday?"
.\.venv\Scripts\python.exe -m jimmy remember "standup is at 10:30 on weekdays"
.\.venv\Scripts\python.exe -m jimmy doctor
```

Jimmy understands times like *today*, *yesterday*, *this morning*, *on Tuesday*
and *last 20 minutes*. A question with a time but no topic ("what was I doing
this morning?") gets a timeline of the apps you had open and what was said.

In chat, `/remember <fact>` keeps something, and **`/context` shows exactly what
was sent to the model** for your last question. Only that text leaves the laptop,
at most 6,000 characters, and only when a key is set. Excluded surfaces (banking,
password managers, private windows) were never captured, so they can't be sent.

### Checks

```powershell
.\.venv\Scripts\python.exe tests\test_stage1.py    # 13 checks, no framework
.\.venv\Scripts\python.exe tests\test_stage2.py    # 13 checks, mocked network
```

OpenCV prints `net_impl_backend ... Targets are not supported` on import. Harmless.

---

## What it stores — and what it refuses to

| Stored | Never stored |
|---|---|
| Window app and title | Any raw, unblurred frame |
| Exact UI text, OCR text | Face embeddings or any biometric template |
| Blurred thumbnails (~27 KB) | Anything from an excluded surface |
| Transcribed speech | Raw audio — only the transcript survives |
| Face **count** per frame | Face identity, names, cross-day links |

Roughly **130 MB per 8-hour day**, most of it thumbnails. There is no retention
policy yet — see `SCOPE.md`.

**Excluded surfaces are never captured at all:** password managers, banking and
payment domains, and private/incognito windows. Add your own in
`data\exclusions.txt`, one per line:

```
exe:mysecret.exe
title:payroll
url:internal\.example\.com
```

**Faces are blurred before anything is written.** The clean frame exists only as a
local variable inside one tick. Faces are told apart *within a single capture
window* so a moment can report how many people were present, and that memory is
dropped when the window closes — the same person tomorrow is a new stranger. There
is no `faces` table and no `people` table, and that absence is the design.

The blur is verified against the detector, not by eye: the test re-runs face
detection on the saved JPEG and requires zero hits.

A face embedding is a biometric template under India's DPDP Act whether or not
it's persisted. This design shrinks exposure substantially. It does not take it
to zero.

**Recording others is off by default.** System/loopback audio is disabled
(`CAPTURE_LOOPBACK = False`) — mic only. Recording the far end of a call is a
consent problem, not a feature flag, and the recording indicator and per-call
opt-out that should accompany it aren't built yet.

**The mic pauses on sensitive surfaces.** While a password manager, banking page or
private window is focused, audio isn't recorded, so an OTP read aloud never
reaches a transcript. The exception is a call: if another app, such as Teams,
Zoom or a browser tab on Meet, is using the mic, recording continues so the
meeting isn't lost.

---

## What's next

Stage 2 is built; its last check is one live answer once an NVIDIA key is set.
Stage 3 builds the trigger gate, which is the
actual product, and it can't ship until a replayed hour produces ten cards or
fewer, every one defensible.

Full status in [`TIMELINE.md`](TIMELINE.md).
