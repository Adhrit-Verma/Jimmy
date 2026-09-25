# Data flow

What moves, in what order, and what is thrown away. The ordering is the privacy
design: several steps exist purely so that something is destroyed before the next
step can write it.

---

## The screen tick — every 2 s

```
 1. active_window()              Win32: hwnd, exe, title.  Cheap, no COM.
 2. Exclusions.check(app,title) ─── excluded? ─► STOP. Nothing captured. ─┐
 3. ScreenSource.grab()          DXGI pull. None => desktop unchanged. ───┤
 4. _window_for(app)             live capture window for this app;        │
                                 expires idle/aged windows + their faces  │
 5. signature vs window.last_sig  grey 160x90; < 0.25 % of pixels moved  │
                                 by > 12 levels? ─► STOP (unchanged) ─────┤
 6. window_text(hwnd)            wake_accessibility once, then a bounded  │
                                 BFS: <=1200 nodes, depth 30, 0.6 s;      │
                                 button and menu-item names skipped       │
 7. Exclusions.check(url) ─────── excluded? ─► STOP, discard step 6 ──────┤
 8. FaceStage.process()          detect, embed, BLUR -> `blurred`         │
 9. save_thumb(blurred)          the ONLY frame that touches disk         │
10. add_frame                    always: the frame row is the timeline    │
    add_text(new_lines(...))     only lines this window hasn't stored yet │
11. ocr(blurred) if text < 40ch  inert today: no tesseract binary         │
                                                                          ▼
                                                              counters, console
```

Three things to notice:

- **Step 2 precedes step 3.** An excluded surface is never even captured into
  memory, let alone written.
- **Step 7 exists because of step 6.** A browser's address bar is only readable
  once the UIA tree has been walked, so the URL check must come *after* the text
  is gathered and must discard it.
- **Step 8 precedes step 9.** `bus.tick` passes only `blurred` to `save_thumb`.
  The clean frame is a local variable that dies with the tick.
- **Step 5 is where "worth capturing" is decided, and it has to see text.** The
  first gate, a 64-bit dhash, missed a one-message chat scroll 7 times in 8 (D18).
- **Step 10 stores what's new, not what's visible.** A text block is the lines
  that appeared since the window's earlier captures. To reconstruct "the whole
  screen at 11:00", read that window's blocks up to 11:00, not just the 11:00 one.

`FaceStage.process` returns a copy and leaves the source frame untouched, so the
unblurred frame stays available in memory for consumers that legitimately need it
(shoulder-surf warning) while never being persistable.

---

## The audio path

```
WASAPI stream (48 kHz stereo int16)
        │
        ▼  to_mono16k: average channels, decimate 3:1 (box filter)
16 kHz mono int16
        │
        ▼  VadChunker: 30 ms frames, 5-frame pre-roll, 700 ms silence closes
Segment(ts_start, ts_end, source, pcm)
        │
        ▼  queue(maxsize=64) ─► transcribe thread
        │
        ▼  Transcriber.transcribe
             RMS < 120?                    -> ""   (never decoded)
             no_speech_prob > 0.6?         -> drop segment
             avg_logprob < -1.0?           -> drop segment
             text in HALLUCINATIONS?       -> ""
        │
        ▼  non-empty only
audio_segments row (+ audio_fts index)
```

**Why the filtering exists.** Whisper invents text when handed non-speech. On
this machine, silence decoded as `"you"` and white noise as `"Thanks."` Unfiltered,
that would quietly fill the corpus with utterances nobody said — and then feed the
Stage 3 trigger gate phantom evidence. An empty string is the correct and common
answer.

**Why there is a pre-roll.** Without it every segment opens mid-syllable and the
first word of each utterance is clipped, which measurably hurts transcription.

**Audio pauses on sensitive surfaces (D13).** After every tick, if the focused
surface was excluded and no other app holds the microphone, the bus sets
`AudioPipeline.paused`. The capture threads keep draining the device but drop the
audio, and `VadChunker.reset()` discards the utterance in progress. If another app
holds the mic, which means a call is on, recording continues. A URL-excluded page
stays excluded while its window and title are unchanged, so an idle bank tab
doesn't read as safe.

**Loopback is off by default.** Recording the far end of a call is a consent
problem, not a feature flag. Mic-only is cheaper to design in now than to retrofit.

---

## Schema

Follows `AMBIENT_LAYER.md`. `evidence` is declared `TEXT` rather than the spec's
`JSON`, because SQLite gives an unrecognised type name NUMERIC affinity and would
coerce numeric-looking payloads; the content is still JSON.

```sql
capture_windows(id TEXT PK, opened_at INT, closed_at INT, kind TEXT)
frames(id INT PK, ts INT, window_id TEXT, app TEXT, title TEXT,
       thumb_path TEXT, face_count INT)
text_blocks(id INT PK, frame_id INT, source TEXT /* 'uia' | 'ocr' */, text TEXT)
audio_segments(id INT PK, ts_start INT, ts_end INT, window_id TEXT,
               source TEXT /* 'mic' | 'loopback' */, speaker_ord INT, text TEXT)
cards(id INT PK, ts INT, type TEXT, line TEXT, evidence TEXT, state TEXT)
```

**There is no `faces` table and no `people` table.** That absence is the design,
and `tests/test_stage1.py` asserts it.

`cards` holds every card shown (Stage 3); `state` becomes `dismissed` when × is
clicked in the overlay (Stage 4).

```sql
embeddings(id INT PK, ref INT /* > 0 text_blocks.id, < 0 -audio_segments.id */,
           ts INT, model TEXT, chunk TEXT /* <= 800 chars */, vec BLOB /* float32, unit length */)
```

Stage 5 (D24): a background thread embeds new captures every 60 s with local
bge-m3; `ambient index` backfills. Pruning captures must prune their
embeddings too.

Timestamps are epoch **milliseconds** throughout.

### Full-text search

Two external-content FTS5 tables, `text_fts` over `text_blocks` and `audio_fts`
over `audio_segments`, each kept in step by insert/delete/update triggers.
External content means the index stores no second copy of the text.

`Store.search` unions both and orders by `bm25`, so one query spans what you saw
and what was said:

```
ambient search "trigger gate"
Mon 21 Sep 01:37  [screen/uia]  bus.py - Jimmy
    ...the [trigger] [gate] is a cost control as much as...
Mon 21 Sep 01:41  [audio/mic]   mic
    ...tune the [trigger] [gate] before stage four...
```

---

## What is stored, and what is not

| Stored | Not stored |
|---|---|
| Window app name and title | Any raw, unblurred frame |
| Exact UI text (UIA), OCR text | Face embeddings or any biometric template |
| Blurred thumbnails (~27 KB each) | Anything from an excluded surface |
| Transcribed speech, with source | Raw audio — only the transcript survives |
| Face **count** per frame | Face identity, names, or cross-window links |
| Capture window open/close times | Any link between a person today and tomorrow |

**Footprint:** the first real hour, under the old gate, was **2.0 MB/h** (~26 KB
per thumbnail, 96 % of ticks skipped), i.e. ~0.5 GB for 8 h/day for 30 days. The
finer D18 gate captures more, because it stops missing scrolls and new messages,
so that is a floor. Re-measure from the next run. The text DB is negligible
beside the images, and smaller still now that only new lines are stored.

---

## Asking Jimmy (Stage 2)

```
question ─► Jimmy.ask
  1. memory.recall(question)          fts_query → memories_fts, top 5
  2. AmbientPlugin.context(question)
       time_window(question)          day ("yesterday", "on Tuesday") and/or clock
                                      ("between 10:40 and 11:10", "at 3pm", "after 11")
       search_captures ─► Store.search(fts_query, since, until, 48-token snippets)
       if a time was named OR nothing matched:
         coverage(frame_times)        FIRST: "N captures; nothing captured 10:47–10:59 …"
         Store.activity(window)       app/title, first + last seen, how many captures
         Store.speech(window)         what was said
  3. render_context                   dedupe, ≤ 6000 chars, priority order:
                                      memory → coverage → keyword hits → activity → speech
  4. messages = system rules + <context>…</context>
              + last 6 chat turns + the question
  5. llm.chat_stream (chat)  ─► NVIDIA ─► <think> stripped ─► shown token by token
     llm.chat (Jimmy.ask)    ─► the same, returned whole
  6. both turns saved to jimmy.db
```

**Why a coverage line.** Captures are samples, not a recording. Without being told
where the holes are, the model filled a 15-minute uncaptured stretch with "an
active conversation" (D18). Coverage names every gap of 5+ minutes as unknown, and
it goes ahead of everything else so the context budget can't cut it off.

**Only step 5 leaves the laptop**, and only when a key is set. What it carries is
exactly `render_context`'s output, which `/context` in chat prints verbatim.
Without a key, step 5 is skipped and the answer is that same context, marked
offline.

**Why `fts_query` quotes every word.** Questions are free text, and FTS5 treats
`NOT`, `OR`, `NEAR(`, `*` and stray quotes as syntax. Unquoted, "C++ is NOT
working" is a query error, or a different query. Quoted and OR-joined, any
question is a valid search, and filler words ("what", "earlier", weekday names)
are dropped first. A question with no topic words skips keyword search and gets
the activity timeline instead.

### Jimmy's memory schema (`data/jimmy.db`)

```sql
memories(id INT PK, ts INT, source TEXT, text TEXT)   -- + memories_fts (external content)
turns(id INT PK, ts INT, session TEXT, role TEXT /* 'user' | 'assistant' */, text TEXT)
```

A separate file from `ambient.db` on purpose: captures will be pruned by a
retention policy one day, and memory must not be.

---

## The trigger gate (Stage 3)

```
frame / speech ─► Gate (Tier 1)
  moment = one (app, title) stretch; ends when the window changes
    drop screen furniture: lines already seen in ≥ 3 capture windows (D22)
    ended, ≥ 60 s and ≥ 200 chars of what's left?
      words(moment) − stopwords − GENERIC
      keep rare ones: 0 < share ≤ 3 % of text blocks BEFORE the moment start
      Store.search(OR of up to 6, until = moment start − 2 h: a different sitting)
      hit in another window, sharing ≥ 2 stems, not used before?  ─► Candidate RECALL
  speech ends in "?" (4+ words) ─► same lookup ─► Candidate RECALL
  intent stated, nothing related for 10 min, no FOCUS card for 45 min ─► Candidate FOCUS
  limits: cooldown · ≤ 4 cards/h · ≥ 10 min gap · no repeat · ≤ 20 candidates/h
Candidate ─► CardEngine (Tier 2): <now> + <evidence> ─► model, thinking on
  reply ─► last JSON {"speak", "line", "why"} ─► line ≤ 7 words? ─► Card
Card ─► cards(ts, type, line, evidence JSON, state='shown') + console
```

Tier 2 runs on the local model (D20), so card decisions stay on the laptop. The
exception is a RECALL the local model says yes to: that one candidate's "now"
(≤ 1,500 chars) and the matched earlier item go to the cloud model for a second
opinion (D22). On the recorded data, that happened a few times in 1.18 h.

---

## Ephemerality, concretely

A face embedding is a biometric template under India's DPDP Act whether or not it
is persisted. The design shrinks exposure rather than pretending to eliminate it:

- Vectors live in `FaceStage._vectors`, keyed by capture window id.
- Comparison happens **within one window only**, cosine ≥ 0.363.
- When the window closes — idle 120 s, or 15 min old — the dict entry is dropped.
- `FaceStage` raises `TypeError` on `__getstate__` and `__reduce__`, so it cannot
  be pickled into a cache, a log, or a subprocess by accident.
- Nothing survives the process.

The same person tomorrow is a new stranger with no link to today. That is the
whole point, and it is why the counts are per-window ordinals ("face 1, face 2")
rather than identifiers.
