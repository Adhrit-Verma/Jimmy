# Timeline

Stage status against `AMBIENT_LAYER.md`. Update the status line and the gate
result whenever either changes.

```
 [x] 0  Pre-flight              resolved 2026-09-21
 [x] 1  Context bus             built 2026-09-21, acceptance met
 [ ] 1b Face stage              built; threshold untuned against real footage
 [~] 2  Jimmy core + hookup     built 2026-09-21; live check waits on an NVIDIA key
 [ ] 3  Trigger gate + cards    not started — this is the product
 [ ] 4  Overlay                 not started — gated on stage 3 GO
 [ ] 5  Recall timeline         not started — mostly free once 1 exists
```

---

## Stage 0 — Pre-flight · **done**

The spec's first open question was whether `C:\Code\Jimmy` was really empty.

**It is.** Searched every `package.json` under `C:\Code` outside `node_modules`:
22 Node projects, none of them Jimmy. There is no existing Jimmy tree, no memory
store, no RAG, no NVIDIA LLM client, no plugin system. The folder contained
`AMBIENT_LAYER.md` and nothing else.

**Consequence:** Stage 1 is greenfield and does not depend on Jimmy, so it was
built standalone. The human decided the Jimmy core is built here, in this repo
(D14).

Hardware confirmed against the spec's assumptions: Ryzen 7 7840HS, RTX 4050
Laptop with 6141 MiB VRAM, CUDA 12.4. The spec's constraints hold.

Exclusion list shipped before first run, as non-negotiable 4 requires.

---

## Stage 1 — Context bus · **done, acceptance met**

> **Acceptance:** a full working day is captured and queryable by text, and no
> unblurred face exists anywhere on disk.

**Queryable by text — met.** A 60 s run captured 10 frames and 9 text blocks;
`ambient search` returns highlighted snippets across both screen text and speech
from one query. A single frame yielded 4,359 characters of exact UIA text.

**No unblurred face on disk — met, and asserted.** `bus.tick` passes only the
blurred frame to `save_thumb`. `test_blur_defeats_redetection` re-runs the
detector on the saved artifact, including after the JPEG round-trip: 2 faces in,
0 findable out.

*"A full working day"* has not been run end to end — the longest run so far is
60 s. Nothing in the design should prevent it, but it is unproven, and the
retention policy it will need does not exist yet. That is the honest status.

**Verification:** 12/12 checks pass in `tests\test_stage1.py`. `doctor` reports
every component green except OCR.

**Measured:** DXGI ~8 ms/frame · UIA 317 nodes / 4.8k chars / ~230 ms · Whisper
347 MiB VRAM, ~60× realtime · ~27 KB/thumbnail, ~130 MB/8-hour day · ~65 % of
ticks skipped as perceptually unchanged.

**Two bugs found and fixed during the build**, both of which looked fine until
measured — worth remembering as the pattern:
- UIA depth capped at 12 silently discarded all Chromium page content (D4).
- Blur that looked convincing left the face re-detectable in the saved JPEG (D7).

---

## Stage 1b — Face stage · **built, not yet tuned**

Mechanism is complete: YuNet detect, SFace embed, per-capture-window dict, cosine
0.363, blur before write, dict dropped when the window closes. `FaceStage` refuses
to serialise.

**Outstanding:** the threshold is OpenCV's reference value, not a measurement.
On synthetic faces two visibly different drawings matched as one person. It needs
tuning against real webcam footage before the count means anything beyond
"blur here".

The capture-window boundary — the spec's second open question, and the only
tunable it says changes behaviour — is now **one window per app, expiring after
120 s idle or 15 min age** (D6). "Call end" as a boundary awaits call detection.

---

## Stage 2 — Jimmy core + hookup · **built; live acceptance waits on a key**

> **Acceptance:** the sidecar gets a useful answer from Jimmy without
> instantiating its own LLM client.

Stage 0 found no Jimmy tree, so the core was built here (D14) in Python (D16):
the one LLM client, memory in `data/jimmy.db`, and the plugin seam. The ambient
layer is loaded as Jimmy's first plugin. The spec's FastAPI bridge moved to
Stage 4, because with both halves in Python nothing crosses a process yet.

**"Without its own LLM client": met, and enforced.** `test_only_one_llm_client`
fails if anything in `ambient/` imports an HTTP library or builds an `LLM`.

**"A useful answer": met against a mocked network, not yet live.**
`test_ask_end_to_end_is_the_stage2_acceptance` runs the real client through
`httpx.MockTransport`. It checks that captured screen text and memory reach the
prompt inside `<context>`, below the untrusted-data rule, and that the streamed
answer comes back and is saved. Run against the real `data/ambient.db` in offline
mode, keyword questions, time questions ("today") and remembered facts all
retrieved correctly.

**Still owed:** one live round trip with a real key, and a judgement on whether
the answers are *useful*. `jimmy doctor` does the round trip and times it.

**Verification:** 12/12 in `tests\test_stage2.py`; Stage 1 still 13/13.

---

## Stage 3 — Trigger gate + card engine · **not started · this is the product**

Spend the most time here. Ships to a console log, no UI.

Tier 1 is local rules plus a small model deciding whether anything changed enough
to be worth speaking, with a hard rate limit, a cooldown after dismissal, and no
repeats in a session. Tier 2 turns a surviving delta into silence or exactly one
card: `TIP`, `FOCUS`, `ACTION` or `RECALL`.

The `cards` table already exists and is unused — that is the seam.

> **GO / NO-GO:** replay one recorded hour of real screen history. It must
> produce **≤10 cards**, and you must be willing to defend every one. If it wants
> to fire more, tune the gate and replay. **Do not proceed to Stage 4.**

Stage 1 makes this replay possible: an hour of real history is now recordable and
queryable, which is exactly what the gate has to be tuned against.

---

## Stage 4 — Overlay · **not started · gated**

Electron, transparent, always-on-top, `WS_EX_TRANSPARENT` click-through,
per-monitor DPI, no taskbar entry. Pill at top-centre, cards top-right. Must
include "pause for 2 hours" and a global pause hotkey.

**Do not start until the Stage 3 GO gate passes.**

---

## Stage 5 — Recall timeline · **not started · mostly free**

> **Acceptance:** answers "what was that thing I saw on Tuesday".

Most of it already exists: FTS5 is in place over both screen text and speech, and
the thumbnails are already blurred, timestamped and on disk. What is missing is
embeddings for semantic hits and a scrub UI.

---

## Next, in order

1. ~~Human call: where is Jimmy?~~ Built here (D14).
2. ~~Human call: audio during excluded surfaces~~ Pause unless a call (D13, built).
3. Run Stage 1 for a genuine working day; size a retention policy from the result.
4. Install Tesseract to close the canvas/video gap.
5. Tune the face threshold against real footage.
6. ~~Stage 2: Jimmy core + hookup~~ Built 2026-09-21.
7. **Human: get an NVIDIA key** and set `NVIDIA_API_KEY`. Then `jimmy doctor`
   and a real chat close Stage 2, and measure the default model (D16).
8. Benchmark a local 3B LLM on the 4050 (D15), then Stage 3, and spend the time there.

Ideas beyond this list live in `SCOPE.md` → Possible future changes.
