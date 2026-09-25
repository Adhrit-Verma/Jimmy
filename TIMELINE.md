# Timeline

Stage status against `AMBIENT_LAYER.md`. Update the status line and the gate
result whenever either changes.

```
 [x] 0  Pre-flight              resolved 2026-09-21
 [x] 1  Context bus             built 2026-09-21, acceptance met
 [ ] 1b Face stage              built; threshold untuned against real footage
 [x] 2  Jimmy core + hookup     built 2026-09-21, live acceptance met 2026-09-22
 [~] 3  Trigger gate + cards    built 2026-09-25; GO on count, card review owed (D19)
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

*"A full working day"* has not been run end to end yet. The longest run is the
first real hour (66 min, 2026-09-22), which ran clean. It also exposed six
problems, fixed in D18: a change gate blind to text, chrome boilerplate,
re-stored text, clock times, over-inference and a silent mic nobody noticed.
The data was wiped afterwards for a fresh start under the fixed pipeline.

**Verification:** 15/15 checks pass in `tests\test_stage1.py`. `doctor` reports
every component green except OCR, and its mic test heard speech (peak 9,678).

**Measured:** DXGI ~8 ms/frame · UIA 317 nodes / 4.8k chars / ~230 ms · Whisper
347 MiB VRAM, ~60× realtime · first real hour: 2.0 MB/h, 96 % of ticks skipped
under the old gate (a floor: the D18 gate captures more).

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

## Stage 2 — Jimmy core + hookup · **done, acceptance met live**

> **Acceptance:** the sidecar gets a useful answer from Jimmy without
> instantiating its own LLM client.

Stage 0 found no Jimmy tree, so the core was built here (D14) in Python (D16):
the one LLM client, memory in `data/jimmy.db`, and the plugin seam. The ambient
layer is loaded as Jimmy's first plugin. The spec's FastAPI bridge moved to
Stage 4, because with both halves in Python nothing crosses a process yet.

**"Without its own LLM client": met, and enforced.** `test_only_one_llm_client`
fails if anything in `ambient/` imports an HTTP library or builds an `LLM`.

**"A useful answer": met live on 2026-09-22.** With a real key and the real
capture DB, three questions were answered correctly: what happened yesterday
(the right apps at the right times), screen text about "the sidebar", and a fact
from memory. Each named when and where, and nothing was invented. Offline, and
through `httpx.MockTransport` in
`test_ask_end_to_end_is_the_stage2_acceptance`, the same path is checked on every
test run.

**Caveat:** the data was a single one-minute capture. This proves the path, not
recall quality over a real working day, which is still owed (item 3 below).

**It took a model change to get here.** The first default leaked its reasoning
and took 19 s to 159 s. The benchmarked replacement, `nemotron-3-super-120b` with
thinking off, answers in **~1 s to first word** (D17). `jimmy doctor` now fails a
reply that isn't the word it asked for, and flags slow latency.

**Verification:** 13/13 in `tests\test_stage2.py`; Stage 1 still 13/13; `jimmy
doctor` all green, 0.81 s to first word.

---

## Stage 3 — Trigger gate + card engine · **built · GO on count, review owed**

> **GO / NO-GO:** replay one recorded hour of real screen history. It must
> produce **≤10 cards**, and you must be willing to defend every one. If it wants
> to fire more, tune the gate and replay. **Do not proceed to Stage 4.**

Built 2026-09-25 (D19): RECALL + FOCUS, Tier 1 local rules (`ambient/gate.py`),
Tier 2 the cloud model (`jimmy/cards.py`), live in `ambient run` (console +
`cards` table) and in `ambient replay`. TIP (web search) and ACTION (approval
flow) come after the gate passes.

**Replay, 1.18 h of real history (two sessions, 25 + 46 min), local qwen2.5:3b
deciding (D20):** 5 candidates → **1 card**, "Same Sunandha UI/UX resume as Tue
15:02". Worst hour: 1. **GO on count.** With a stated intent: 2 FOCUS nudges,
then the 45-min hold. (The earlier cloud-written cards are superseded: code now
writes every card from the evidence.)

**Still owed before the GO is real:**
1. The human reads those cards and says whether each is defensible.
2. One *continuous* recorded hour, as the spec asks (the longest so far is 46 min).
3. A replay with a real stated intent (`jimmy focus`), so FOCUS is judged on
   real behaviour. The FOCUS replay so far used a made-up intent.

**Verification:** 9/9 in `tests\test_stage3.py`; Stages 1 and 2 still 15/15, 14/14.

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
3. **Now:** run capture for a few hours on the fixed pipeline (D18), speaking now
   and then. Re-measure MB/h, replay, and re-ask recall questions. That session
   is also the replay data Stage 3's GO gate is tuned against.
4. Install Tesseract to close the canvas/video gap.
5. Tune the face threshold against real footage.
6. ~~Stage 2: Jimmy core + hookup~~ Built 2026-09-21.
7. ~~Human: get an NVIDIA key~~ Set; Stage 2 closed live, model measured (D17).
8. Benchmark a local 3B LLM on the 4050 (D15), then Stage 3, and spend the time there.

Ideas beyond this list live in `SCOPE.md` → Possible future changes.
