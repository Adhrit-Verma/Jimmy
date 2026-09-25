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
                 overlay: bool = True):
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
        self.paused_until = 0          # epoch ms; the overlay's "pause for 2 hours"
        self._api = None
        self._overlay_proc = None
        self._asker = None          # voice / typed questions (D25), set up with the overlay
        self._voice = None
        self._speaking = False

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
        status = self._tick()
        self._apply_audio_policy(sensitive=(status == "excluded"))
        return status

    def _apply_audio_policy(self, sensitive: bool) -> None:
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
            why = "Jimmy speaking" if speaking else "sensitive surface"
            print(f"[audio] {'paused: ' + why if pause else 'resumed'}")
        if pause:
            self.counters.audio_paused_ticks += 1

    def _tick(self) -> str:
        c = self.counters
        c.ticks += 1
        ts = now_ms()

        aw = screen.active_window()
        reason = self.exclusions.check(app=aw.app, title=aw.title)
        # A page excluded by URL stays excluded while it's the same window and
        # title; otherwise an unchanged banking tab would skip the walk and
        # read as safe on the next tick.
        if not reason and self._sensitive_key == (aw.hwnd, aw.title):
            reason = self._sensitive_reason
        if reason:
            c.skipped_excluded += 1
            c.excluded_reasons[reason] = c.excluded_reasons.get(reason, 0) + 1
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
        frame_id = self.store.add_frame(w.id, aw.app, aw.title, thumb, face_count, ts)

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
        return "captured"

    # --- audio -----------------------------------------------------------
    def _on_audio(self, ts_start: int, ts_end: int, source: str, text: str) -> None:
        # "Jimmy, …" is a question for Jimmy: stored as a command, never evidence
        # (D27: "can you listen to me" once answered with itself), and not for the gate.
        command = bool(self._asker and self._asker.hear(ts_end, source, text))
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
            card_id = self.store.add_card(card.type, card.line, card.evidence, card.ts)
            print(f"\n[card] {card.type}: {card.line}   ({card.why})\n")
            if self._api:
                self._api.publish({"type": "card", "id": card_id, "kind": card.type,
                                   "line": card.line, "ts": card.ts})

        def on_decision(cand, card, why):
            if card is None:
                print(f"[gate] {cand.type} candidate ({cand.reason}) -> {why}")

        self._gate_memory = Memory(jcfg.MEMORY_DB)
        return Gate(self.store, engine, self._gate_memory, on_card=on_card,
                    on_decision=on_decision, background=True, history_until=now_ms())

    # --- overlay (Stage 4) ------------------------------------------------
    def overlay_state(self) -> dict:
        paused = now_ms() < self.paused_until
        return {"paused": paused, "paused_until": self.paused_until if paused else 0,
                "cards": self.gate is not None}

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
        from .recall import timeline_hooks
        self._voice = Voice(on_start=self._voice_started, on_end=self._voice_ended) \
            if config.VOICE_ANSWERS else None
        self._api = OverlayAPI({"state": self.overlay_state, "pause": self.pause,
                                "resume": self.resume, "dismiss": self.dismiss,
                                "post_ask": lambda b: self._asker.ask(str(b.get("q", "")).strip(), "typed")
                                if str(b.get("q", "")).strip() else None,
                                "post_stop-voice": lambda b: self._voice and self._voice.stop(),
                                "post_quit": lambda b: self.stop_running(),
                                **timeline_hooks(self.store)}).start()
        self._asker = Asker(self.store, self._api.publish,
                            speak=self._voice.say if self._voice else None,
                            screen_now=self.screen_now)
        env = dict(os.environ, JIMMY_OVERLAY_URL=self._api.url, JIMMY_OVERLAY_TOKEN=self._api.token)
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
        print("[overlay] up. Say \"Jimmy, …\" to ask; Ctrl+Alt+Space to type; Ctrl+Alt+J pauses")

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
        self._speaking = False             # the next tick's audio policy resumes the mic

    def stop_running(self) -> None:
        """Quit from the overlay: the same clean shutdown as Ctrl-C."""
        print("[bus] quit requested from the overlay")
        self._running = False

    def _stop_overlay(self) -> None:
        if getattr(self, "_voice", None):
            self._voice.close()
        if self._overlay_proc and self._overlay_proc.poll() is None:
            self._overlay_proc.terminate()
        if self._api:
            self._api.stop()
            self._api = None

    def _index_loop(self) -> None:
        """Embed new captures for meaning search once a minute (Stage 5, D24).
        If the embedding model is unavailable, keyword search still works; retry later."""
        from jimmy.core import LLMError

        from .recall import index
        while self._running:
            for _ in range(config.INDEX_EVERY_S):
                if not self._running:
                    return
                time.sleep(1)
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
