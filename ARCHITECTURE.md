# Architecture

Stages 1 and 2. Stages 3–5 are sketched at the end as boundaries to design toward,
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

Stage 1 stops at the store. Stage 2 puts Jimmy on top of it:

```
                you ──► python -m jimmy chat / ask
                                  │
                                  ▼
        ┌──────────────────── Jimmy.ask ─────────────────────┐
        │  memory.recall  ◄── data/jimmy.db (facts, turns)   │
        │  plugins ──► AmbientPlugin ◄── data/ambient.db     │  read-only
        │                 time phrase → bounded FTS           │
        │                 no topic → activity + speech        │
        │  render_context (≤ 6000 chars, inside <context>)    │
        │  llm.chat ──► NVIDIA API (the ONE client) ──► text  │
        └─────────────────────────────────────────────────────┘
```

There is still no gate, no card engine and no overlay, deliberately: the gate is
the product and deserves to be built against real captured data.

## Jimmy core (Stage 2)

| Module | Responsibility | Notable choice |
|---|---|---|
| `jimmy/llm.py` | the only LLM client | one reused httpx client (warm connection); streams; strips `<think>`; retries once, never mid-stream |
| `jimmy/memory.py` | remembered facts + chat turns | its own SQLite file so capture retention can never prune memory; `fts_query` quotes every term |
| `jimmy/core.py` | `Jimmy.ask`, prompt, plugin seam | a plugin is just `name` + `context()` + `tools`; no discovery, since there is one |
| `ambient/plugin.py` | captures → snippets | turns "yesterday", "on Tuesday", "last 20 min" into a time window; never creates the capture DB |

**Direction of dependency:** the ambient layer depends on the core (the plugin
imports `jimmy`), never the reverse at load time. `Jimmy.default()` is the one
place that imports the plugin.

**Two processes, one database file each, no server.** `ambient run` writes
`ambient.db`; `jimmy chat` reads it concurrently. SQLite WAL mode allows exactly
that. The spec's FastAPI bridge existed to join a Node Jimmy to a Python sidecar;
with both in Python it had no job, so it moved to Stage 4 (D16).

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

## Trigger gate (Stage 3)

```
 bus.tick ── captured frame (app, title, new lines) ──┐
 audio worker ── transcribed speech ──────────────────┤
                                                      ▼
                        ambient/gate.py  Gate (Tier 1, local rules, no LLM)
                          moment ends → RECALL lookup (past only, rare words)
                          question heard → RECALL lookup
                          stated intent + 10 min drift → FOCUS
                          hard limits: 4/h, 10-min gap, 20 candidates/h, no repeats
                                                      │ Candidate
                                          queue(32) → worker thread "gate-tier2"
                                                      ▼
                        jimmy/cards.py  CardEngine (Tier 2)
                          typed questions → local qwen2.5:3b via Ollama (default)
                            FOCUS: {"related"}   RECALL, per item: {"same", "thing"}
                          RECALL yes → cloud model re-asks the same question (D22)
                          code writes the line: "Same <thing> as <Tue 15:02>"
                            (thing must be in the evidence; time = its timestamp)
                                                      ▼
                        console "[card] …"  +  cards table
```

Tier 2 runs on its own thread so a cloud call (1–3 s, longer with thinking) never
delays a capture tick. `ambient replay` drives the *same* `Gate` from
`Store.events()` synchronously. Every lookup is bounded to before the moment in
question, so replay can't see the future and tuning in replay transfers to live.
The dependency direction holds: `ambient/gate.py` imports `jimmy.cards`, never
`jimmy.llm`, and the engine is built by `jimmy.cards.default_engine()`.

## Overlay (Stage 4)

```
 ambient run ──► OverlayAPI  127.0.0.1:<free port>, token per run (env only)
     │             GET /events (SSE: state, card)   POST pause|resume|toggle-pause|dismiss
     └─ spawns ──► Electron main (overlay/main.cjs): the only network client
                     transparent, click-through, focusable:false, no taskbar, on top
                     Ctrl+Alt+J → toggle-pause; quits ~15 s after capture stops
                       │ IPC (preload.cjs: 3 functions)
                       ▼
                   page (React + Tailwind + Motion): pill top-centre, ≤ 3 cards top-right
                     sandboxed, no Node, CSP connect-src 'none'
```

A card flows: `Gate` → `on_card` → `cards` table + `OverlayAPI.publish` → SSE →
Electron main → IPC → the page. Dismissal flows back: × → IPC → main → POST
`/dismiss` → `cards.state = 'dismissed'` + `Gate.dismissed()` (30-min cooldown).

## Boundaries for later stages

- **Stage 3 continues** with TIP (web search provider) and ACTION (an approval
  step, never straight from model output), once RECALL/FOCUS pass the GO gate.
- **Stage 4 follow-ups:** multi-monitor, a chat panel in the overlay, auto-start
  with Windows, an installer (D23).
- **Stage 5 (recall timeline)** is mostly free: FTS5 is already in place, the
  thumbnails are already blurred and already on a timeline.
