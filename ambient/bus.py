"""The context bus: the one loop that ties capture, redaction and storage together.

Stage 1 has no UI and no LLM. It captures a working day and makes it queryable.
The screen loop runs on the calling thread because UI Automation is COM and is
happiest where it was initialised; audio runs on its own threads.
"""
from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config, screen
from .db import Store, now_ms
from .redact import Exclusions, FaceStage


@dataclass
class _Window:
    """A live capture window. `last_sig` is per-app so that returning to an
    untouched app does not write the same screen twice; `seen_lines` is every
    text line already stored for this window, so only new lines get stored."""
    id: str
    opened: float
    last_seen: float
    last_sig: np.ndarray | None = None
    seen_lines: set[str] = field(default_factory=set)
    last_thumb: str | None = None      # D31: reused when you switch back to an unchanged screen
    last_url: str | None = None


def new_lines(text: str, seen: set[str]) -> str:
    """The lines of `text` not stored before in this window, in screen order.

    In the first real hour 52 % of captures re-stored near-identical text. Now
    the first capture of a window stores the screen, and later ones only what's
    new. ponytail: `seen` lives as long as the capture window (<= 15 min), so a
    line that reappears after the window rolls is stored again. That's intended.
    """
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


@dataclass
class Counters:
    ticks: int = 0
    frames: int = 0
    skipped_unchanged: int = 0
    switch_frames: int = 0
    skipped_excluded: int = 0
    skipped_no_frame: int = 0
    text_blocks: int = 0
    ocr_blocks: int = 0
    audio_segments: int = 0
    audio_paused_ticks: int = 0
    faces_blurred: int = 0
    windows: int = 0
    excluded_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["excluded_reasons"] = dict(self.excluded_reasons)
        return d


class ContextBus:
    def __init__(self, db_path: str | Path | None = None, monitor: int | None = None,
                 audio: bool = True, thumbs: bool = True, cards: bool = True,
                 overlay: bool = True, demo: str | None = None):
        import cv2
        cv2.setNumThreads(config.CV_THREADS)    # D38: same outputs, a third of the CPU
        self.store = Store(db_path or config.DB_PATH)
        self.exclusions = Exclusions(config.EXCLUSIONS_FILE)
        self.faces = FaceStage()
        self.source = screen.ScreenSource(monitor)
        self.want_audio = audio
        self.want_thumbs = thumbs
        self.counters = Counters()
        self.window_id: str | None = None
        self._open: dict[str, _Window] = {}   # app -> its live capture window
        self._sensitive_key: tuple[int, str] | None = None
        self._sensitive_reason = ""
        self._running = False
        self._audio = None
        self.gate = self._make_gate() if cards else None
        self.want_overlay = overlay
        self.demo = demo            # D28: a script to play for screen recordings
        self.paused_until = 0          # epoch ms; the overlay's "pause for 2 hours"
        self._api = None
        self._overlay_proc = None
        self._asker = None          # voice / typed questions (D25), set up with the overlay
        self._voice = None
        self._speaking = False
        self._curtain = False         # D34: the privacy curtain is down: nothing is captured
        self._manual_curtain = False
        self._presence = {"state": "off"}
        self._presence_obj = None
        self._sensitive = False       # the last tick was an excluded surface or a password box
        self._proactive = None        # D32
        self._last_frame_ts = None

    # --- capture windows -------------------------------------------------
    def _expire_windows(self, now: float, ts: int, keep: str | None = None) -> None:
        """Close windows that went idle or aged out, forgetting their faces."""
        for app, w in list(self._open.items()):
            idle = (now - w.last_seen) >= config.WINDOW_IDLE_S
            old = (now - w.opened) >= config.WINDOW_MAX_S
            if (idle or old) and app != keep:
                self.store.close_window(w.id, ts)
                self.faces.close_window(w.id)  # the dict dies here, with the window
                del self._open[app]

    def _window_for(self, app: str, ts: int) -> "_Window":
        """The live window for this app, opening one if it has none."""
        now = time.monotonic()
        self._expire_windows(now, ts)
        w = self._open.get(app)
        if w is not None and (now - w.opened) < config.WINDOW_MAX_S:
            w.last_seen = now
            return w
        if w is not None:  # aged out while focused: roll it
            self.store.close_window(w.id, ts)
            self.faces.close_window(w.id)
        w = _Window(id=self.store.open_window(kind="app", ts=ts), opened=now, last_seen=now)
        self._open[app] = w
        self.counters.windows += 1
        return w

    # --- one tick --------------------------------------------------------
    def tick(self) -> str:
        """Returns a short status word, for the console and for tests."""
        if now_ms() < self.paused_until:
            # User pause: nothing is captured at all, screen or audio.
            if self._audio and not self._audio.paused.is_set():
                self._audio.paused.set()
            return "paused"
        if screen.is_locked():
            # D32: locked means away. The screen shows nothing of yours; the mic would
            # only hear an empty room (or someone else's).
            self._apply_audio_policy(sensitive=True, why="locked")
            return "locked"
        if getattr(getattr(self, "_presence_obj", None), "enrolling", False):
            # D37: the guided capture shows your face on screen; never capture that.
            return "enrolling"
        if getattr(self, "_curtain", False):
            # D34: the curtain covers the screen, so a capture would store the curtain.
            # D39: and if it's down because you left, Jimmy rests: the mic pauses too
            # (unless a call is on). A curtain you drew yourself keeps listening.
            self._apply_audio_policy(sensitive=self.dormant(), why="you're away")
            return "curtained"
        status = self._tick()
        sensitive = status == "excluded"
        if sensitive != getattr(self, "_sensitive", False):
            self._sensitive = sensitive
            self._refresh_curtain()         # someone looking + a bank page -> curtain
        self._apply_audio_policy(sensitive=sensitive)
        return status

    def _apply_audio_policy(self, sensitive: bool, why: str = "sensitive surface") -> None:
        """Pause audio on a sensitive surface -- unless a call is on (D9).

        A spoken OTP must not be transcribed, but glancing at a bank tab mid-call
        must not silently drop the meeting either. "A call is on" means another
        app holds the microphone.

        ponytail: decided once per tick, so up to one interval (2 s) of audio
        before the pause can still get through as a finished segment; the
        utterance in progress is dropped. Tighten with a faster poll if that
        window matters.
        """
        if not self._audio:
            return
        from .audio import other_app_using_mic
        speaking = getattr(self, "_speaking", False)   # D25: never transcribe Jimmy's own voice
        pause = speaking or (sensitive and not other_app_using_mic())
        if pause != self._audio.paused.is_set():
            (self._audio.paused.set if pause else self._audio.paused.clear)()
            why = "Jimmy speaking" if speaking else why
            print(f"[audio] {'paused: ' + why if pause else 'resumed'}")
        if pause:
            self.counters.audio_paused_ticks += 1

    def _tick(self) -> str:
        c = self.counters
        c.ticks += 1
        ts = now_ms()

        aw = screen.active_window()
        reason = self.exclusions.check(app=aw.app, title=aw.title)
        if not reason and screen.focused_is_password():
            reason = "password field"            # D32: typing a password: like a bank page
        # A page excluded by URL stays excluded while it's the same window and
        # title; otherwise an unchanged banking tab would skip the walk and
        # read as safe on the next tick.
        if not reason and self._sensitive_key == (aw.hwnd, aw.title):
            reason = self._sensitive_reason
        if reason:
            c.skipped_excluded += 1
            c.excluded_reasons[reason] = c.excluded_reasons.get(reason, 0) + 1
            self._last_seen = None         # coming back is a switch, even to an unchanged screen
            return "excluded"

        frame = self.source.grab()
        if frame is None:
            c.skipped_no_frame += 1
            return "no-frame"

        # Looking at the app keeps its window alive, whether or not the pixels moved.
        w = self._window_for(aw.app, ts)
        self.window_id = w.id

        sig = screen.signature(frame)
        if w.last_sig is not None and screen.changed_pct(sig, w.last_sig) < config.GATE_CHANGED_PCT:
            c.skipped_unchanged += 1
            # D31: back to a window whose screen didn't change. Without a row, time on
            # screen kept counting for the app you left. One row, the thumbnail already
            # on disk, no text, no gate: the switch is all it records.
            if (aw.app, aw.title) != getattr(self, "_last_seen", None) and w.last_thumb:
                self.store.add_frame(w.id, aw.app, aw.title, w.last_thumb, 0, ts, w.last_url)
                self._last_seen = (aw.app, aw.title)
                c.switch_frames += 1
                self._captured(ts)
                return "switched"
            return "unchanged"

        wt = screen.window_text(aw.hwnd) if aw.hwnd else screen.WindowText("", "", 0, 0.0, False)

        # Second exclusion pass: the address bar is only readable once we walk
        # the tree, and a banking URL must discard everything gathered above.
        reason = self.exclusions.check(url=wt.url) if wt.url else None
        if reason:
            c.skipped_excluded += 1
            c.excluded_reasons[reason] = c.excluded_reasons.get(reason, 0) + 1
            w.last_sig = sig
            self._sensitive_key, self._sensitive_reason = (aw.hwnd, aw.title), reason
            return "excluded"

        # Faces are destroyed before anything is written. `frame` never reaches disk.
        blurred, face_count, _ordinals = self.faces.process(frame, w.id)
        c.faces_blurred += face_count

        thumb = screen.save_thumb(blurred, ts) if self.want_thumbs else None
        # D32: the page's address, to reopen it later. Only reached past both
        # exclusion checks; query and fragment dropped (screen.clean_url).
        url = screen.clean_url(wt.url) if wt.url else None
        frame_id = self.store.add_frame(w.id, aw.app, aw.title, thumb, face_count, ts, url)

        # The frame row is always written (it's the timeline); text only if new.
        fresh = new_lines(wt.text, w.seen_lines)
        if self.store.add_text(frame_id, "uia", fresh):
            c.text_blocks += 1
        if len(wt.text) < config.UIA_MIN_CHARS:
            text = screen.ocr(blurred)  # blurred, so OCR can never read a face
            ocr_new = new_lines(text, w.seen_lines)
            if self.store.add_text(frame_id, "ocr", ocr_new):
                c.ocr_blocks += 1
                fresh = "\n".join(p for p in (fresh, ocr_new) if p)
        if self.gate:
            self.gate.observe_frame(ts, aw.app, aw.title, w.id, fresh)

        c.frames += 1
        w.last_sig = sig
        w.last_thumb, w.last_url, self._last_seen = thumb, url, (aw.app, aw.title)
        self._captured(ts)
        return "captured"

    def _captured(self, ts: int) -> None:
        """A frame row was written. Back after a long gap? (D32: "Left off: …")"""
        prev, self._last_frame_ts = getattr(self, "_last_frame_ts", None), ts
        if getattr(self, "_proactive", None):
            self._proactive.on_capture(ts, prev)

    # --- audio -----------------------------------------------------------
    def _on_audio(self, ts_start: int, ts_end: int, source: str, text: str) -> None:
        # "Jimmy, …" is a question for Jimmy: stored as a command, never evidence
        # (D27: "can you listen to me" once answered with itself), and not for the gate.
        command = bool(self._asker and self._asker.hear(ts_end, source, text, ts_start))
        self.store.add_audio(ts_start, ts_end, "command" if command else source, text,
                             window_id=self.window_id)
        self.counters.audio_segments += 1
        if command:
            return
        if self.gate:
            self.gate.observe_speech(ts_start, ts_end, source, text)

    # --- trigger gate (Stage 3) ------------------------------------------
    def _make_gate(self):
        """Tier 1 here, Tier 2 in a worker thread so a cloud call never delays a tick.
        Cards go to the console and the `cards` table; there is no UI until Stage 4."""
        from jimmy import config as jcfg
        from jimmy.cards import default_engine
        from jimmy.memory import Memory

        from .gate import Gate
        engine = default_engine()
        if not engine.llm.configured:
            engine = None                      # Tier 1 still runs and logs candidates

        def on_card(card):
            card_id = self.store.add_card(card.type, card.line, card.evidence, card.ts, app=self._app_now())
            print(f"\n[card] {card.type}: {card.line}   ({card.why})\n")
            if self._api:
                # `at`: the earlier moment a RECALL points to, so the card can open it (D31).
                at = next((e["ts"] for e in card.evidence if e.get("ts")), None)
                self._api.publish({"type": "card", "id": card_id, "kind": card.type,
                                   "line": card.line, "ts": card.ts, "at": at, "why": card.why})

        def on_decision(cand, card, why):
            if card is None:
                print(f"[gate] {cand.type} candidate ({cand.reason}) -> {why}")

        self._gate_memory = Memory(jcfg.MEMORY_DB)
        return Gate(self.store, engine, self._gate_memory, on_card=on_card,
                    on_decision=on_decision, background=True, history_until=now_ms(),
                    muted=self._muted)

    # --- D32: cards Jimmy writes itself, and learning from dismissals ------
    def _app_now(self) -> str | None:
        from .insights import app_name
        seen = getattr(self, "_last_seen", None)
        return app_name(seen[0]) if seen and seen[0] else None

    def _muted(self, kind: str) -> bool:
        return self.store.muted(kind, self._app_now(), now_ms() - config.MUTE_WINDOW_DAYS * 86_400_000,
                                config.MUTE_AFTER_DISMISSALS)

    def _show_card(self, kind: str, line: str, payload: dict) -> None:
        if self._muted(kind):
            print(f"[card] {kind} muted here: {line}")
            return
        ts = now_ms()
        card_id = self.store.add_card(kind, line, payload, ts, app=self._app_now())
        print(f"\n[card] {kind}: {line}\n")
        if self._api:
            self._api.publish({"type": "card", "id": card_id, "kind": kind, "line": line, "ts": ts, **payload})

    # --- D34: the privacy curtain ------------------------------------------
    def _on_presence(self, info: dict) -> None:
        old = self._presence
        self._presence = info
        if old.get("state") != info.get("state"):
            print(f"[presence] {info['state']}{' (' + info['why'] + ')' if info.get('why') else ''}")
            self._refresh_curtain(force=True)
        elif old.get("contact") != info.get("contact"):
            self._publish_presence()           # D39: the pill shows when Jimmy sees you looking

    def dormant(self) -> bool:
        """D39: the curtain is down because you left (or someone else sat down), so
        Jimmy rests: no capture, no listening, no indexing, no cards of its own.
        Presence keeps looking for you; reminders and timers still ring."""
        return bool(getattr(self, "_curtain", False) and not getattr(self, "_manual_curtain", False)
                    and (getattr(self, "_presence", None) or {}).get("state") in ("away", "stranger"))

    def curtain_now(self) -> bool:
        presence = getattr(self, "_presence", None) or {}
        st = presence.get("state")
        if getattr(self, "_manual_curtain", False):
            return True
        if st == "away" and config.CURTAIN_WHEN_AWAY:
            return True
        if st == "stranger" and config.CURTAIN_WHEN_STRANGER:
            return True                         # D37: someone who isn't you, at your screen
        if st == "watched":
            mode = config.CURTAIN_WHEN_WATCHED
            return mode == "always" or (mode == "sensitive" and self._sensitive)
        return False                            # D39: where you look never curtains; leaving does

    def _on_enrol(self, ev: dict) -> None:
        """The guided capture's progress (D37): to the overlay every frame, to your ears
        when the instruction changes and has held a moment (not every frame)."""
        if self._api:
            self._api.publish({"type": "enrol", **ev})
        say, now = ev.get("say", ""), time.monotonic()
        last = getattr(self, "_enrol_said", ("", 0.0))
        if ev.get("done") or (say and say != last[0] and now - last[1] > 2.5):
            self._enrol_said = (say, now)
            if self._voice and say:
                self._voice.say(say)
        if ev.get("done"):
            self._enrol_said = ("", 0.0)
            if self._api:
                self._api.publish({"type": "state", **self.overlay_state()})

    def set_volume(self, word: str, mem) -> str:
        """"Jimmy, speak softer / louder / mute your voice" (D35), remembered."""
        v = self._voice
        if not v:
            return "My voice is switched off in config."
        if word in ("mute", "unmute"):
            v.muted = word == "mute"
            said = "Muted. Say \"Jimmy, unmute your voice\" to hear me." if v.muted else "I'm back."
        else:
            v.volume = max(10, min(100, v.volume + (20 if word == "louder" else -20)))
            said = f"Volume {v.volume} percent."
        mem.set_setting("voice_volume", v.volume)
        mem.set_setting("voice_muted", int(v.muted))
        return said

    def set_curtain(self, on: bool) -> None:
        """By hand: Ctrl+Alt+L, the pill, or "Jimmy, curtain" / "lift the curtain"."""
        self._manual_curtain = on
        if not on and self._presence.get("state") in ("away", "watched"):
            self._presence = {**self._presence, "state": "present"}   # you're here: you just asked
        self._refresh_curtain(force=True)

    def _refresh_curtain(self, force: bool = False) -> None:
        on = self.curtain_now()
        if on == getattr(self, "_curtain", False) and not force:
            return
        self._curtain = on
        rest = self.dormant()
        if rest != (getattr(self, "_dormant_since", None) is not None):
            self._dormant_since = time.monotonic() if rest else None
            print("[bus] resting while you're away: capture, listening, indexing paused" if rest
                  else "[bus] awake")
            if not rest and getattr(self, "_audio", None):
                self._apply_audio_policy(sensitive=getattr(self, "_sensitive", False))   # at once
        self._publish_presence()

    def _publish_presence(self) -> None:
        if getattr(self, "_api", None):
            self._api.publish({"type": "presence", "state": self._presence.get("state"),
                               "watched": self._presence.get("state") == "watched",
                               "curtain": self._curtain, "manual": self._manual_curtain,
                               "contact": bool(self._presence.get("contact") and self._eyes_on()),
                               "why": self._presence.get("why", "")})

    def _eyes_on(self) -> bool:
        """D39: talking to Jimmy by looking at the screen, unless you said "name only"."""
        mem = self._intent_memory()
        return (mem.setting("eye_contact", "1" if config.EYE_CONTACT_ASKS else "0") == "1") if mem \
            else config.EYE_CONTACT_ASKS

    def set_eye_mode(self, on: bool) -> None:
        mem = self._intent_memory()
        if mem:
            mem.set_setting("eye_contact", int(on))
        self._publish_presence()

    def forget(self, since: int, until: int, label: str) -> str:
        """D39: "delete everything from September", after your yes. Captures, the
        pictures on disk, and Jimmy's chat turns from then; then the space comes back."""
        n = self.store.measure(since, until)
        self.store.forget(since, until)
        mem = self._intent_memory()
        if mem:
            mem.forget_turns(since, until)
        before, after = self.store.compact()
        print(f"[db] forgot {label}: {n['frames']} frames, {n['speech']} lines; "
              f"database {before / 1e6:.1f} -> {after / 1e6:.1f} MB, pictures -{n['bytes'] / 1e6:.0f} MB")
        return f"Deleted {label}: freed {(n['bytes'] + max(0, before - after)) / 1e6:,.0f} MB."

    def _maybe_compact(self) -> None:
        """D39: tidy the database while you're away, at most once a day."""
        since = getattr(self, "_dormant_since", None)
        mem = self._intent_memory()
        if (not since or not mem or getattr(self, "_compacting", False)
                or time.monotonic() - since < config.COMPACT_AFTER_AWAY_S
                or now_ms() - int(float(mem.setting("last_compact", 0))) < config.COMPACT_EVERY_H * 3600_000):
            return
        self._compacting = True

        def go():
            try:
                before, after = self.store.compact()
                mem.set_setting("last_compact", now_ms())
                print(f"[db] compacted while you were away: {before / 1e6:.1f} -> {after / 1e6:.1f} MB")
            except Exception as exc:
                print(f"[db] compact: {type(exc).__name__}: {exc}")
            finally:
                self._compacting = False
        threading.Thread(target=go, daemon=True, name="compact").start()

    # --- overlay (Stage 4) ------------------------------------------------
    def overlay_state(self) -> dict:
        from jimmy import config as jcfg
        paused = now_ms() < self.paused_until
        mem = self._intent_memory()
        soon = now_ms() + config.TIMER_SHOW_S * 1000
        return {"paused": paused, "paused_until": self.paused_until if paused else 0,
                "cards": self.gate is not None,
                "focus": mem.current_intent(jcfg.FOCUS_INTENT_MAX_H) if mem else None,
                # D39: timers and reminders due soon count down on the pill
                "timers": [{"id": r["id"], "text": r["text"], "due": r["due_ts"]} for r in mem.reminders()
                           if r["due_ts"] and r["due_ts"] <= soon][:2] if mem else [],
                **({"curtain": self._curtain, "presence": self._presence.get("state"),
                    "owner": bool(self._presence_obj and self._presence_obj.owner.known)}
                   if getattr(self, "_presence_obj", None) or getattr(self, "_manual_curtain", False) else {})}

    def _intent_memory(self):
        return getattr(self, "_gate_memory", None) or getattr(self, "_focus_memory", None)

    def set_focus(self, text: str | None) -> None:
        """What you mean to be doing (FOCUS cards), from the pill or "Jimmy, focus on …" (D31)."""
        mem = self._intent_memory()
        if mem:
            mem.set_intent(text)
            print(f"[bus] focus: {text or '(cleared)'}")

    def pause(self, minutes: float) -> None:
        self.paused_until = now_ms() + int(minutes * 60_000)
        print(f"[bus] paused for {minutes:.0f} min")

    def resume(self) -> None:
        self.paused_until = 0
        print("[bus] resumed")

    def dismiss(self, card_id: int) -> None:
        """A card waved away in the overlay: record it, and quiet the gate for a while."""
        self.store.set_card_state(card_id, "dismissed")
        if self.gate:
            self.gate.dismissed(now_ms())

    def _start_overlay(self) -> None:
        """Serve the local API and launch the Electron overlay, if it's been built."""
        import os
        import subprocess
        from .api import OverlayAPI
        root = config.ROOT / "overlay"
        exe = root / "node_modules" / "electron" / "dist" / "electron.exe"
        if not (root / "dist" / "index.html").exists() or not exe.exists():
            print("[overlay] not built: cd overlay && npm install && npm run build")
            return
        from .ask import Asker, Voice
        from .audio import other_app_using_mic
        from .recall import timeline_hooks
        self._voice = Voice(on_start=self._voice_started, on_end=self._voice_ended) \
            if config.VOICE_ANSWERS else None
        if not self.gate:                  # --no-cards: a stated focus still needs a home
            from jimmy import config as jcfg
            from jimmy.memory import Memory
            self._focus_memory = Memory(jcfg.MEMORY_DB)
        mem = self._intent_memory()        # focus and reminders (D32) live in Jimmy's memory
        if self._voice:                    # D35: the volume you asked for last time
            self._voice.volume = int(mem.setting("voice_volume", config.VOICE_VOLUME))
            self._voice.muted = mem.setting("voice_muted") == "1"
        self._api = OverlayAPI({"state": self.overlay_state, "pause": self.pause,
                                "resume": self.resume, "dismiss": self.dismiss,
                                "post_ask": lambda b: self._asker.ask(str(b.get("q", "")).strip(), "typed")
                                if str(b.get("q", "")).strip() else None,
                                "post_stop-voice": lambda b: self._voice and self._voice.stop(),
                                "post_quit": lambda b: self.stop_running(),
                                "post_clarify": lambda b: self._asker.choose(str(b.get("choice", ""))),
                                "post_focus": lambda b: self.set_focus(str(b.get("text", "")).strip() or None),
                                "post_curtain": lambda b: self.set_curtain(bool(b.get("on"))),
                                "post_card_used": lambda b: self.store.set_card_state(int(b.get("id", 0)), "used"),
                                "post_scroll_window": lambda b: screen.scroll_active(b.get("dir") != "up"),
                                "post_accept": lambda b: self._api.publish(
                                    {"type": "toast", "text": self._asker.accept(), "icon": "yes"}),
                                **timeline_hooks(self.store)}).start()
        self._asker = Asker(self.store, self._api.publish,
                            speak=self._voice.say if self._voice else None,
                            screen_now=self.screen_now,
                            actions={"pause": self.pause, "resume": self.resume, "focus": self.set_focus,
                                     "hush": self._voice.stop if self._voice else (lambda: None),
                                     "state": self.overlay_state, "curtain": self.set_curtain,
                                     "remind": lambda what, due, app: mem.add_reminder(what, due, app),
                                     "reminders": lambda: mem.reminders(),
                                     "cancel_reminder": lambda rid: mem.set_reminder_state(rid, "cancelled"),
                                     # D39: what the camera saw while a line was said; delete a span
                                     "spoke": lambda a, b: self._presence_obj.spoke(a, b) if self._presence_obj else None,
                                     "facing": lambda a, b: (self._presence_obj.facing_during(a, b)
                                                             if self._presence_obj else None),
                                     "eye_contact": lambda a, b: bool(self._presence_obj
                                                                      and self._presence_obj.eye_contact(a, b)),
                                     "eyes_on": self._eyes_on, "eye_mode": self.set_eye_mode,
                                     "on_call": other_app_using_mic,
                                     "voice_on": lambda: bool(self._voice and not self._voice.muted),
                                     "measure": self.store.measure, "forget": self.forget,
                                     "unremind": lambda: mem.set_reminder_state(None, "cancelled"),
                                     "open_file": os.startfile,
                                     "volume": lambda word: self.set_volume(word, mem),
                                     "presence": lambda: self._presence if self._presence_obj else None,
                                     "enrol": lambda: self._presence_obj.enrol() if self._presence_obj
                                     else "The webcam is switched off in config (PRESENCE).",
                                     "unenrol": lambda: self._presence_obj.forget() if self._presence_obj
                                     else "The webcam is switched off in config (PRESENCE).",
                                     "cancel_enrol": lambda: self._presence_obj and self._presence_obj.cancel_enrol()})
        # D32: the cards Jimmy writes itself. Deadlines need the local model.
        from jimmy.cards import local_engine

        from .proactive import Proactive
        engine = local_engine() if config.DEADLINE_SCAN_S else None
        self._proactive = Proactive(self.store, mem, self._show_card,
                                    offer=lambda kind, data: self._asker.make_offer(kind, data),
                                    say=self._voice.say if self._voice else None,
                                    is_deadline=engine.is_deadline if engine else None)
        # D34: presence from the webcam, for the privacy curtain.
        if config.PRESENCE:
            from .presence import Presence
            self._presence_obj = Presence(self._on_presence, on_enrol=self._on_enrol).start()
        env = dict(os.environ, JIMMY_OVERLAY_URL=self._api.url, JIMMY_OVERLAY_TOKEN=self._api.token)
        # Started from an Electron app's terminal (VS Code, Claude), this is inherited
        # and makes electron.exe run as plain Node: no window, "app.whenReady" undefined.
        env.pop("ELECTRON_RUN_AS_NODE", None)
        # Piped: a GUI program's console output goes nowhere on Windows unless it is,
        # and page errors must reach this terminal (D26).
        self._overlay_proc = subprocess.Popen(
            [str(exe), str(root)], env=env, cwd=str(root), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")

        def relay(stream):
            for line in stream:
                line = line.rstrip()
                if line.startswith("[overlay") or "rror" in line or "panel failed" in line:
                    print(line if line.startswith("[") else f"[overlay] {line}")
        threading.Thread(target=relay, args=(self._overlay_proc.stdout,), daemon=True,
                         name="overlay-log").start()
        print("[overlay] up. Say \"Jimmy, …\" to ask; Ctrl+Alt+Space to type; Ctrl+Alt+J pauses; "
              "Ctrl+Alt+T timeline; Ctrl+Alt+I insights")

    def screen_now(self) -> dict | None:
        """The window the user is on right now: its latest frame and everything it
        has shown, for "what's on my screen?" (D27). None for excluded or unseen."""
        aw = screen.active_window()
        if self.exclusions.check(app=aw.app, title=aw.title):
            return None                   # banking, password managers, Jimmy itself
        w = self._open.get(aw.app)
        if w is None:
            return None
        frame, text = self.store.window_content(w.id, aw.title)
        return {"frame": frame, "text": text} if frame else None

    def _voice_started(self) -> None:
        self._speaking = True
        if self._audio:
            self._audio.paused.set()       # at once, not at the next tick

    def _voice_ended(self) -> None:
        self._speaking = False
        if getattr(self, "_asker", None):
            self._asker.voice_done()        # D39: go on without the name for a few seconds
        # D38: the mic came back at the next tick, up to 2 s later, and a quick "next"
        # or a reply to Jimmy's question was lost. Back in 0.25 s (the room's echo of
        # the voice has died by then), with the same checks a tick makes.
        threading.Timer(0.25, self._resume_after_voice).start()

    def _resume_after_voice(self) -> None:
        if getattr(self, "_speaking", False) or not self._audio:
            return
        if now_ms() < self.paused_until or screen.is_locked():
            return                         # paused or locked: the tick keeps the mic off
        self._apply_audio_policy(sensitive=getattr(self, "_sensitive", False))

    def stop_running(self) -> None:
        """Quit from the overlay: the same clean shutdown as Ctrl-C."""
        print("[bus] quit requested from the overlay")
        self._running = False

    def _stop_overlay(self) -> None:
        if getattr(self, "_presence_obj", None):
            self._presence_obj.stop()
        if getattr(self, "_voice", None):
            self._voice.close()
        if self._overlay_proc and self._overlay_proc.poll() is None:
            self._overlay_proc.terminate()
        if self._api:
            self._api.stop()
            self._api = None
        if getattr(self, "_focus_memory", None):
            self._focus_memory.close()
            self._focus_memory = None

    def _index_loop(self) -> None:
        """Embed new captures for meaning search once a minute (Stage 5, D24).
        If the embedding model is unavailable, keyword search still works; retry later."""
        from jimmy.core import LLMError

        from .recall import index
        # D38: load the embedding model and open the cloud connection now, not on the
        # first question (which waited ~6 s for bge-m3 and a fresh TLS handshake).
        try:
            from jimmy.core import embed
            embed(["warm up"])
        except Exception:
            pass
        if self._asker is not None:
            try:
                self._asker._jim().llm.warm()
            except Exception as exc:
                print(f"[ask] warm-up: {type(exc).__name__}: {exc}")
        while self._running:
            for _ in range(config.INDEX_EVERY_S):
                if not self._running:
                    return
                time.sleep(1)
            if self.dormant():
                continue                     # D39: resting while you're away; nothing new anyway
            try:
                index(self.store, limit=200)
            except LLMError:
                pass
            except Exception as exc:   # indexing must never take capture down
                print(f"[index] {type(exc).__name__}: {exc}")

    # --- run -------------------------------------------------------------
    def run(self, duration_s: float | None = None, verbose: bool = True) -> Counters:
        self._running = True
        started = time.monotonic()
        if self.want_overlay:
            try:
                self._start_overlay()
            except Exception as exc:  # the overlay is optional; capture must go on
                print(f"[overlay] disabled: {type(exc).__name__}: {exc}")
        threading.Thread(target=self._index_loop, daemon=True, name="indexer").start()
        if self.demo and self._api:
            from . import demo
            script = None if self.demo == "default" else Path(self.demo).read_text(encoding="utf-8")
            threading.Thread(target=demo.run, args=(self, script), daemon=True, name="demo").start()

        if self.want_audio:
            from .audio import AudioPipeline
            self._audio = AudioPipeline(self._on_audio)
            try:
                self._audio.start()
                if verbose:
                    t = self._audio.transcriber
                    print(f"[audio] {t.name} on {t.device}/{t.compute}"
                          f"{' | ' + '; '.join(self._audio.errors) if self._audio.errors else ''}")
            except Exception as exc:
                print(f"[audio] disabled: {type(exc).__name__}: {exc}")
                self._audio = None

        def _halt(*_):
            self._running = False
        try:
            signal.signal(signal.SIGINT, _halt)
        except ValueError:
            pass  # not the main thread

        if verbose:
            print(f"[bus] capturing every {config.FRAME_INTERVAL_S}s -> {self.store.path}")
            print(f"[bus] faces={'on' if self.faces.available else 'MODELS MISSING'} "
                  f"ocr={'on' if screen.ocr_available() else 'off (no tesseract)'}  ctrl-c to stop")

        last_report = 0.0
        try:
            while self._running:
                if duration_s and (time.monotonic() - started) >= duration_s:
                    break
                t0 = time.monotonic()
                try:
                    status = self.tick()
                    rest = status == "curtained" and self.dormant()
                    if self._proactive and status != "paused":
                        seen = getattr(self, "_last_seen", None) or ("", "")
                        self._proactive.tick(now_ms(), *seen, quiet=rest)   # D39: away: reminders only
                    if rest:
                        self._maybe_compact()
                except Exception as exc:
                    status = f"error:{type(exc).__name__}:{exc}"
                if verbose and (status.startswith("error") or time.monotonic() - last_report > 10):
                    last_report = time.monotonic()
                    c = self.counters
                    print(f"[{time.strftime('%H:%M:%S')}] {status:10s} "
                          f"frames={c.frames} text={c.text_blocks} audio={c.audio_segments} "
                          f"skip(unchanged/excluded)={c.skipped_unchanged}/{c.skipped_excluded}")
                time.sleep(max(0.0, config.FRAME_INTERVAL_S - (time.monotonic() - t0)))
        finally:
            self.close(verbose=verbose)
        return self.counters

    def close(self, verbose: bool = False) -> None:
        self._running = False
        self._stop_overlay()
        if self._audio:
            self._audio.stop()
            if verbose and self._audio.errors:
                for e in self._audio.errors[-5:]:
                    print(f"[audio] {e}")
        if self.gate:
            self.gate.flush(now_ms())
            self.gate.close()
            self._gate_memory.close()
        for w in self._open.values():
            self.store.close_window(w.id)
            self.faces.close_window(w.id)
        self._open.clear()
        self.faces.reset()   # nothing survives the process, by design
        self.store.close()
