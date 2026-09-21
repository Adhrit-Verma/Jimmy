# Architecture

Stage 1 only. Stages 2–5 are sketched at the end as boundaries to design toward,
not as things that exist. Spec: `AMBIENT_LAYER.md`.

---

## The shape of it

```
 SOURCES                        PIPELINE                          OUTPUT

 active window (Win32) ────┐
 screen frame (2s, DXGI) ──┤──► REDACT ──► CONTEXT BUS ──► [stage 3: TRIGGER GATE]
 mic audio (WASAPI) ───────┤      │            │
 (loopback, off by default)┘      │            ▼
                                  │        SQLite + FTS5
                                  │        blurred thumbnails
                                  ▼
                          exclusions + face blur
                          (before any write)
```

Stage 1 stops at the store. There is no gate, no card engine, no overlay and no
LLM anywhere in this codebase yet — deliberately, because the gate is the product
and it deserves to be built against real captured data rather than guesses.

---

## Why the screen becomes text immediately

The hard constraint is 6 GB of VRAM. Transcription and OCR fit locally; a
vision-language model does not fit alongside them. So the screen is converted to
*text* as early as possible and only text travels onward:

1. **UI Automation first.** Exact strings, not OCR guesses. This is the Windows
   advantage over the macOS reference product.
2. **OCR second**, and only for canvas-rendered apps and video, where UIA has
   nothing to say.

The consequence for later stages: whatever Jimmy reasons about is text, and the
token budget is therefore controllable at the source.

### Chromium is the load-bearing detail

Chromium keeps its accessibility engine switched off until an assistive
technology asks for it, and while it is off the renderer exposes *nothing* —
measured here as 24 nodes cold versus 317 once woken. Since browsers and Electron
apps are most of a working day's screen, UIA would be near-useless without this.
`screen.wake_accessibility()` sends the standard `WM_GETOBJECT` / `OBJID_CLIENT`
signal once per window, with `SendMessageTimeoutW` + `SMTO_ABORTIFHUNG` so a
wedged app cannot stall the capture loop.

The cost is real and lands on the observed app: it now builds and maintains an
accessibility tree. That is the price of exact text, and it is the same price
every screen reader charges.

---

## Components

| Module | Responsibility | Notable choice |
|---|---|---|
| `config.py` | every tunable in one place | values carry their reasoning inline; the physical world needs knobs a minimal model can't see |
| `db.py` | SQLite + FTS5 | one connection behind one lock; external-content FTS so the index stores no second copy |
| `redact.py` | exclusions + face stage | the two jobs that answer "what must never reach disk", kept together |
| `screen.py` | frames, change gate, text, thumbnails | pull-based DXGI; Win32 for window identity, UIA only for content |
| `audio.py` | capture, VAD, transcription | loopback off by default; decoder output filtered for hallucinations |
| `bus.py` | the one loop, capture-window lifecycle | screen on the calling thread, audio on its own |
| `__main__.py` | `run` / `search` / `stats` / `doctor` | `doctor` reports what actually works on this machine |

---

## Threading

```
main thread ──► bus.run() ──► tick() every 2s
                                 └─ Win32 + UIA + DXGI + cv2 + SQLite write

audio-mic    ──► WASAPI read ──► to_mono16k ──► VadChunker ──┐
                                                             ├─► queue(64)
audio-loopback (disabled by default) ────────────────────────┘        │
                                                                      ▼
transcribe   ──► Whisper ──► filter ──► SQLite write (same lock)
```

The screen loop stays on the **calling thread** because UI Automation is COM and
is happiest where it was initialised. Audio gets its own threads because WASAPI
reads block, and transcription gets one more so a slow decode can never delay a
frame.

The store is shared across all of them behind a single `RLock`. At a handful of
writes per second contention is not real; the lock is marked as the deliberate
ceiling it is.

---

## Capture windows

A *capture window* is a stretch of working in one app. It is the lifetime that
bounds face differentiation, and `AMBIENT_LAYER.md` flags its boundary as the one
open decision that changes behaviour.

**One window per app, kept alive while you keep coming back to it.** A window
closes when it goes untouched for `WINDOW_IDLE_S` (120 s) or ages past
`WINDOW_MAX_S` (15 min). When it closes, its face vectors are dropped with it.

The first implementation closed the window on every app switch, and it was wrong:
alt-tabbing minted a new window per frame, so the face dict was discarded before
it could ever tell two people apart. See `DECISIONS-AND-WHY.md` D6.

---

## Redaction is structural, not a setting

Two mechanisms, both ahead of any write:

**Exclusions** refuse whole surfaces — password managers, banking, private
windows. Checked twice per tick, because a browser's URL is only readable once
the UIA tree has been walked, and a banking URL must discard everything gathered
above it.

**The face stage** detects with YuNet, embeds with SFace, and keeps vectors in an
in-memory dict keyed by capture window. Both run on CPU in a couple of
milliseconds, so neither competes with Whisper for VRAM. The dict is never
serialised — `FaceStage` raises on `__getstate__`/`__reduce__` — never written,
never logged. Faces are destroyed *before* the frame is saved, so the stored
artifact has never contained one.

Blur strength was set by measurement, not by eye: the first version looked
convincing and the detector still found the face in the saved JPEG. See D7.

---

## Boundaries for later stages

- **Stage 2 (Jimmy core + hookup)** builds the Jimmy core in this repo (D14):
  the NVIDIA LLM client, memory/RAG and the plugin seam. It then adds FastAPI on
  `127.0.0.1` and loads this layer as a plugin. There is exactly **one** LLM
  client and **one** memory store, and both belong to the core. Nothing in
  Stage 1 instantiates a model that would tempt you to add a second.
- **Stage 3 (trigger gate)** reads from the store and writes `cards`. The table
  already exists and is unused — that is the seam.
- **Stage 4 (overlay)** is Electron and talks to the sidecar over the same
  local API. It must not open until the Stage 3 GO gate passes.
- **Stage 5 (recall timeline)** is mostly free: FTS5 is already in place, the
  thumbnails are already blurred and already on a timeline.
