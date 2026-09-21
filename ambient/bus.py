"""The context bus: the one loop that ties capture, redaction and storage together.

Stage 1 has no UI and no LLM. It captures a working day and makes it queryable.
The screen loop runs on the calling thread because UI Automation is COM and is
happiest where it was initialised; audio runs on its own threads.
"""
from __future__ import annotations

import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, screen
from .db import Store, now_ms
from .redact import Exclusions, FaceStage


@dataclass
class _Window:
    """A live capture window. `last_hash` is per-app so that returning to an
    untouched app does not write the same screen twice."""
    id: str
    opened: float
    last_seen: float
    last_hash: int | None = None


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
                 audio: bool = True, thumbs: bool = True):
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
        pause = sensitive and not other_app_using_mic()
        if pause != self._audio.paused.is_set():
            (self._audio.paused.set if pause else self._audio.paused.clear)()
            print(f"[audio] {'paused: sensitive surface' if pause else 'resumed'}")
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

        h = screen.dhash(frame)
        if w.last_hash is not None and screen.hamming(h, w.last_hash) <= config.DHASH_MAX_DISTANCE:
            c.skipped_unchanged += 1
            return "unchanged"

        wt = screen.window_text(aw.hwnd) if aw.hwnd else screen.WindowText("", "", 0, 0.0, False)

        # Second exclusion pass: the address bar is only readable once we walk
        # the tree, and a banking URL must discard everything gathered above.
        reason = self.exclusions.check(url=wt.url) if wt.url else None
        if reason:
            c.skipped_excluded += 1
            c.excluded_reasons[reason] = c.excluded_reasons.get(reason, 0) + 1
            w.last_hash = h
            self._sensitive_key, self._sensitive_reason = (aw.hwnd, aw.title), reason
            return "excluded"

        # Faces are destroyed before anything is written. `frame` never reaches disk.
        blurred, face_count, _ordinals = self.faces.process(frame, w.id)
        c.faces_blurred += face_count

        thumb = screen.save_thumb(blurred, ts) if self.want_thumbs else None
        frame_id = self.store.add_frame(w.id, aw.app, aw.title, thumb, face_count, ts)

        if wt.text and self.store.add_text(frame_id, "uia", wt.text):
            c.text_blocks += 1
        if len(wt.text) < config.UIA_MIN_CHARS:
            text = screen.ocr(blurred)  # blurred, so OCR can never read a face
            if text and self.store.add_text(frame_id, "ocr", text):
                c.ocr_blocks += 1

        c.frames += 1
        w.last_hash = h
        return "captured"

    # --- audio -----------------------------------------------------------
    def _on_audio(self, ts_start: int, ts_end: int, source: str, text: str) -> None:
        self.store.add_audio(ts_start, ts_end, source, text, window_id=self.window_id)
        self.counters.audio_segments += 1

    # --- run -------------------------------------------------------------
    def run(self, duration_s: float | None = None, verbose: bool = True) -> Counters:
        self._running = True
        started = time.monotonic()

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
        if self._audio:
            self._audio.stop()
            if verbose and self._audio.errors:
                for e in self._audio.errors[-5:]:
                    print(f"[audio] {e}")
        for w in self._open.values():
            self.store.close_window(w.id)
            self.faces.close_window(w.id)
        self._open.clear()
        self.faces.reset()   # nothing survives the process, by design
        self.store.close()
