# Timeline

Stage status against `AMBIENT_LAYER.md`. Update the status line and the gate
result whenever either changes.

```
 [x] 0  Pre-flight              resolved 2026-09-21
 [x] 1  Context bus             built 2026-09-21, acceptance met
 [ ] 1b Face stage              built; threshold untuned against real footage
 [x] 2  Jimmy core + hookup     built 2026-09-21, live acceptance met 2026-09-22
 [x] 3  Trigger gate + cards    done 2026-09-25: all 5 checks pass, blind-judged (D22)
 [x] 4  Overlay                 built 2026-09-25: Electron pill + cards, pause, hotkey (D23)
 [x] 5  Recall timeline         done 2026-09-25: hybrid search + timeline window, acceptance met (D24)
 [x] +  Insights + commands     built 2026-10-02: day map, usage answers, voice/typed commands (D31)
 [x] +  Autonomy + curtain      built 2026-10-02: own cards, hands-free UI, privacy curtain (D32–D34)
 [x] +  First-session fixes     built 2026-10-02: routing, tool use, ask-back, scroll, volume, declutter (D35)
 [x] +  English and Hindi only  built 2026-10-02 (D36)
 [x] +  Remember my face        built 2026-10-02: guided capture, DPAPI template, spec amended (D37)
 [x] +  Performance             done 2026-10-02: roundtable + equivalence checks; search 2.8 s -> 0.5 s (D38)
 [x] +  Live-session fixes      built 2026-10-05: traces, listening windows, slow steps, plans, windows, log (D45)
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

## Stage 3 — Trigger gate + card engine · **done: GO (D22)**

**Closed 2026-09-25 on the recorded data, as the human decided.** Checklist (fixed
before evaluating): replay ≤ 10 cards/h, 0/h, PASS · every shown card
defensible per two blind judges, PASS · Tier 2 precision 0.83 vs blind
consensus (bar 0.80), PASS · recall answers 8/8, 0 invented, PASS · tests
15/14/11 and docs, PASS. Honest limit: no real RECALL match exists in this data,
so RECALL's hit rate is proven only synthetically. The history below is how it
got there.

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

## Stage 4 — Overlay · **built (D23)**

Electron, transparent, always-on-top, `WS_EX_TRANSPARENT` click-through,
per-monitor DPI, no taskbar entry. Pill at top-centre, cards top-right. Must
include "pause for 2 hours" and a global pause hotkey.

**Do not start until the Stage 3 GO gate passes.**

---

## Stage 5 — Recall timeline · **done (D24)**

> **Acceptance:** answers "what was that thing I saw on Tuesday".

Most of it already exists: FTS5 is in place over both screen text and speech, and
the thumbnails are already blurred, timestamped and on disk. What is missing is
embeddings for semantic hits and a scrub UI.

---

## Insights and commands · **built 2026-10-02 (D31)**

Local only, from captures already on disk: the Insights tab (day map, apps,
hours, week), usage questions answered in code, voice/typed commands, shorter
answers, and the overlay feedback pass. Checks: `tests\test_stage6.py` (6).
Live acceptance (the human's run-through, list in the D31 hand-off) is open.

---

## Autonomy, hands-free, curtain · **built 2026-10-02 (D32–D34)**

Cards Jimmy writes itself (welcome back, focus offer, reminders, deadlines,
recap), learned mutes, lock/password protection, Open page, drafts, calendar
events after a yes, voice navigation without the wake word, and the
presence-based privacy curtain. Checks: `tests\test_stage7.py` (11). Live
acceptance (the human's run-through) is open, and so is the owner-recognition
question (D34).

## Live · **built 2026-10-02 (D39)**

A curtain that follows where you sit (only leaving curtains, in 1.5 s), Jimmy
resting while you're away, asking without the name (follow-up and eye contact),
the wake word mid-sentence, "delete everything from September" with a yes,
auto-compaction, timers on the pill. Checks: `tests\test_stage9.py` (12), the
command matrix (149), `tests\eval_tools.py` (39/39). Live acceptance on the real
webcam (the follow match, the gaze zone, lips) is open.

**D40, same evening:** the first live session's misses (Discord's mic read as a
call, an unmeasured lip veto, no visible calibration, a flickering eye, a stale
timeline after a forget, scroll in Claude). Checks: `tests\test_stage9.py` (14),
matrix (154), eval 41/41.

## The research roadmap · **built 2026-10-07 (D47–D52), not measured yet**

All five phases of `docs/RESEARCH-AGENT-2026-10.md`: the footprint (D47), fewer tools,
checked actions and whole-task evals (D48), the policy layer and speculative plan
actions (D49), lighter voice and webcam (D50), recipes, Windows OCR, a local fallback,
OTel traces and MCP recall (D51), and the turn detector, Kokoro, int8 vectors and small
thumbnails (D52). Checks: `tests\test_stage13.py` (24). The cheap, safe items are on;
everything with an unmeasured threshold, a package or a model file is off.
**Open, in this order:** the research doc's phase gates on the laptop: CPU % and step
latency before/after (phase 1); `eval_agent.py` ≥ 124/130, `eval_trajectory.py`, tokens per
step (phases 2–3); then each flagged item with the measurement its `config.py` comment
names, one D-record each.

## The live session of 2026-10-05 · **fixed (D45)**

From the report on that 28-minute session: per-request traces, listening windows
counted from when you began, the call rule shown on the pill, "Timmy", slow agent
steps (fallback model, "the model is slow", "stop" mid-task, "Still working on …"),
plans that go on past a scroll, lone actions that end, stale control numbers refused,
"Yes." to Jimmy's own question, focus for text boxes, window tools, tray popups
skipped, lines cut at "and" joined, the console kept in `data/logs/jimmy.log`, and the
P2 polish. Checks: `tests\test_stage12.py` (27; 0/27 on D44's code), matrix (177).
**Open:** live acceptance on Windows (UIA window tools, omnibox focus, the Whisper
prompt measured on recordings), `eval_agent.py` / `eval_tools.py` re-run with a key,
and ~~the human's call on keeping the name detector live during a pause~~ (decided:
yes, storing nothing; built in D46).

## Model end of life · **fixed 2026-10-03 (D43)**

`nemotron-3-super` was retired mid-day (HTTP 410 on every answer). Chat moved to
`nemotron-3-ultra`, tool picks to `gpt-oss-20b` (120/130 real commands), and a
retired model now falls back instead of failing. Check: `tests\test_stage2.py` (15).

## Jimmy as an agent · **built 2026-10-03 (D42)**

The agent loop, multi-step tasks (stage (b) of mouse/keyboard control, with the
human's "plan once + risky steps"), the decision log, the user wiki (OKF). Gate:
the 130 real commands at ≥ 95 % through rules + agent: **124/130** (baseline 92).
Checks: `tests\test_stage11.py` (9), `tests\eval_agent.py`. Live acceptance on the
human's apps is open: read `python -m jimmy trace` after the next session.

## Hands and eyes · **built 2026-10-03 (D41)**

Understanding in context (every unplaced request picked by the model with the
user's lists), reminders / goals / memories by voice and in a Memory tab,
"listening… / heard" feedback, screen answers that see the picture, and the
virtual cursor: stage (a) of mouse/keyboard control, one action per yes. Checks:
`tests\test_stage10.py` (7), matrix (169), eval 59 cases (every answered case
right in two runs). Live acceptance on the human's apps is open.

---

## Next, in order

**As of 2026-10-02 (end of the D31–D39 sessions):**

0. **Done 2026-10-03 (D42):** stage (b) too: multi-step tasks, plan once + risky
   steps (the human's answer to the open question below).
1. **Mouse/keyboard control ("agentic") — stage (a), single confirmed actions, BUILT
   (D41: the virtual cursor, every action waits for a yes, all apps except excluded
   windows). Stage (b), multi-step tasks with plan approval, waits on the human's
   approval-level answer.** The original design, kept for history:
   Agreed with the human: yes it's possible; do performance first (done, D38).
   The design proposed:
   - **How:** UI Automation, not vision. Read the foreground window's actionable
     controls (buttons, fields, menu items, with names and rects) as a numbered
     list. The cloud model picks one step (click id / type text into id / press
     keys / open app). Jimmy does it, re-reads, and repeats until done or stuck.
     This is Microsoft UFO's approach; no vision model is needed (none fits beside
     Whisper in 6 GB).
   - **Safety (non-negotiable 1, invariant 8):**
     - a visible "Jimmy is driving" mode with Stop ("stop", Esc, or touching the
       mouse aborts);
     - plan approval up front, and a hard stop before anything irreversible
       (send, delete, submit, purchase, post);
     - never in excluded windows, never typing passwords;
     - on-screen text is never an instruction: prompt injection is the main risk
       once Jimmy can click;
     - start with a small list of allowed apps.
     This replaces invariant 12 ("scroll is the only input"), so it needs a D-record.
   - **Stages:** (a) single confirmed actions, then (b) multi-step tasks with
     plan approval.
   - **Open questions for the human (ask before building):**
     1. Approval level: every action, or plan once plus risky steps
        (recommended), or no approval for safe steps?
     2. Which apps first (e.g. Chrome, VS Code, Word, Spotify, Discord)?
2. **The human's live run-through** of D31–D39: test lists were given in chat;
   real-hardware items: remember-my-face capture and stranger curtain with the
   real webcam (`OWNER_MATCH` unmeasured), the camera shared with a Teams/Meet
   call, deadlines over a real evening, scroll falling through to the window in
   front, Hindi commands. D39: does a turned head / looking down keep the
   curtain up and leaving drop it (tune `FOLLOW_MIN` from the console's "last
   match"), does eye contact fire on requests and stay quiet in conversation
   (`GAZE_ZONE`, `MOUTH_MOVING`), the follow-up window's feel (`FOLLOWUP_S`).
3. Performance items waiting on evidence or the owner's call: see `SCOPE.md` →
   "Performance (D38) — done, and NOT done" (WebP, an approximate vector index past
   month ~6, the line-count table, cursor polling).

Earlier list, kept for history:

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
