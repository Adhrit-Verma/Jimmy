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
  ....  mic test        speak now for 3 s into 'Headset Microphone (Realtek(R) Audio)' ...
  ok    audio (wasapi)  Headset Microphone (Realtek(R) Audio): peak 9678, hears speech-level sound
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

Jimmy understands days (*today*, *yesterday*, *this morning*, *on Tuesday*,
*last 20 minutes*) and clock times (*between 10:40 and 11:10*, *at 3pm
yesterday*, *after 11*, *before noon*). A question with a time but no topic
("what was I doing this morning?") gets a timeline of the apps you had open and
what was said. Captures are samples, not a recording, so when there's a gap
Jimmy says nothing is known about it rather than guessing.

In chat, `/remember <fact>` keeps something, and **`/context` shows exactly what
was sent to the model** for your last question. Only that text leaves the laptop,
at most 6,000 characters, and only when a key is set. Excluded surfaces (banking,
password managers, private windows) were never captured, so they can't be sent.

### On screen (Stage 4)

`ambient run` also opens a small overlay: a pill at the top of the screen
("● Jimmy · listening") and, now and then, a card at the top right. It's
transparent and click-through, never takes focus, and has no taskbar button.
Hover the pill for **Pause 2h**, or press **Ctrl+Alt+J** anywhere to pause and
resume; while paused, nothing is captured. Hover a card to keep it, click × to
dismiss it (Jimmy then stays quiet for 30 minutes).

One-time setup, needs Node:

```powershell
cd overlay; npm install; npm run build
```

`ambient run --no-overlay` keeps everything in the terminal.

### Just ask: "Jimmy, …"

While `ambient run` is going, **say "Jimmy," and your question**:

> *"Jimmy, what was that consulting application I saw on Friday?"*

The pill shows *thinking…*, then the answer appears on its own:
- **Right: the answer**, as a short explanation: what it was, when and where,
  and why Jimmy thinks so. It's also **read aloud**; click **Stop voice** to
  silence it.
- **Left: the evidence.** The actual moments, as blurred screenshots with day,
  time, app and page title, and the relevant line with your words highlighted.
  The best match is first and highlighted.

It searches across all your days, or just the one you name ("on Tuesday",
"yesterday afternoon", "between 2 and 3"). **Click any screenshot to see it big.**

Jimmy knows what kind of question you're asking:
- **About the past**, as above: *"Jimmy, what did I read about OAuth yesterday?"*
- **About your screen right now**: *"Jimmy, what's on my screen?"*, *"Jimmy,
  summarise this page."* You get a large view of the window you're on, with the
  answer beside it.
- **Just talking**: *"Jimmy, can you hear me?"*, *"Jimmy, what can you do?"* A
  normal reply, no search.

**It's a conversation.** Within a few minutes of a question, follow up
naturally: after the McKinsey question, *"Jimmy, and when does it close?"* gets
"Monday, October 5th, 11:59 pm".

- Saying just **"Jimmy"** works too: pause, then ask.
- **To type instead:** hover the pill and click **Ask**, or press
  **Ctrl+Alt+Space**.
- **Close an answer** with its ×; otherwise it fades after a minute.

Nothing extra to install: speech recognition is the Whisper model already
listening, and the voice is Windows' own.

### Stopping Jimmy

Any of these shuts it down cleanly: capture stops, the overlay closes, and
everything is saved.
- Hover the pill and click **Quit**.
- Press **Ctrl+C** in the terminal running `ambient run`.
- Closing that terminal window also stops it, but the other two are cleaner.

To pause instead of stopping, use **Pause 2h** or **Ctrl+Alt+J**.

### Timeline (Stage 5)

Hover the pill and click **Timeline**, or press **Ctrl+Alt+T**, to open a window
with your day as a strip of blurred screenshots, one per minute. Step through
with ← and →. Each moment shows what was new on screen and anything heard
nearby.

Search it the way you remember it: *"that consulting application on Friday"*
finds the McKinsey form without you knowing the name. Search matches meaning,
not just words, using the local `bge-m3` model, so nothing leaves the laptop.

```bash
ollama pull bge-m3
```

```bash
.\.venv\Scripts\python.exe -m ambient index
```

The first command is a one-time download. The second indexes history captured
before this existed; after that, `ambient run` indexes as it goes.

### Cards (Stage 3)

While `ambient run` is capturing, Jimmy occasionally shows a card of at most
seven words. **RECALL** links what you just did to a concrete earlier moment
("Same resume review as Tuesday 15:00"). **FOCUS** nudges you back, but only if
you've told Jimmy what you meant to do:

```powershell
.\.venv\Scripts\python.exe -m jimmy focus "finish the stage 3 gate"
.\.venv\Scripts\python.exe -m ambient replay     # what it would have said over your history
```

Silence is the default: at most 4 cards an hour, never two within 10 minutes,
and FOCUS nudges at most once every 45 minutes.

**Card decisions run on your laptop,** through [Ollama](https://ollama.com) with
`qwen2.5:3b`, so screen text stays on the machine. The one exception: before a
RECALL card is shown, the cloud model double-checks it, and only those rare
candidates leave the laptop. Set `JIMMY_RECALL_VERIFY=none` to stay fully local,
at lower accuracy. The model only
answers yes/no questions ("is this the same thing?"); Jimmy writes the card
itself from words in the evidence and real timestamps, so a card can't contain
something made up. Chat answers still use the NVIDIA model. `jimmy doctor`
checks both.

```bash
ollama pull qwen2.5:3b
```

### Checks

```powershell
.\.venv\Scripts\python.exe tests\test_stage1.py    # 15 checks, no framework
.\.venv\Scripts\python.exe tests\test_stage2.py    # 14 checks, mocked network
.\.venv\Scripts\python.exe tests\test_stage3.py    # 11 checks, no network
.\.venv\Scripts\python.exe tests\test_stage4.py    # 5 checks, overlay
.\.venv\Scripts\python.exe tests\test_stage5.py    # 10 checks, recall + voice
```

OpenCV prints `net_impl_backend ... Targets are not supported` on import. Harmless.

---

## What it stores — and what it refuses to

| Stored | Never stored |
|---|---|
| Window app and title | Any raw, unblurred frame |
| Exact UI text, OCR text | Face embeddings or any biometric template |
| Blurred thumbnails (~26 KB) | Anything from an excluded surface |
| Transcribed speech | Raw audio — only the transcript survives |
| Face **count** per frame | Face identity, names, cross-day links |

The first real hour used **2.0 MB**, almost all of it thumbnails. That's about
0.5 GB a month at 8 hours a day. The change detector has since been made more
sensitive, so expect somewhat more. It's all on your own disk, and there's no
retention policy yet (see `SCOPE.md`).

**Which microphone.** Capture uses the Windows default input. `ambient doctor`
asks you to speak for 3 seconds and tells you whether it heard you. To use a
different mic, for example the laptop's own when no headset is on, set
`MIC_DEVICE` in `ambient/config.py` to part of its name, such as
`"Microphone Array"`. If the mic hears nothing speech-loud for 10 minutes while
capturing, it says so once.

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

Stages 1 and 2 are done and checked live. Stage 3 builds the trigger gate, which
is the actual product, and it can't ship until a replayed hour produces ten cards
or fewer, every one defensible. That replay needs a few real hours captured on the
current pipeline first.

Full status in [`TIMELINE.md`](TIMELINE.md).
