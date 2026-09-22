"""Mic and system audio -> VAD-gated segments -> local transcription.

Loopback capture is off by default (config.CAPTURE_LOOPBACK). Recording the far
end of a call is a consent problem, not a feature flag, and mic-only is far
cheaper to design in now than to retrofit -- see the legal note in AMBIENT_LAYER.md.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, NamedTuple

import numpy as np

from . import config

RATE = config.SAMPLE_RATE


class Segment(NamedTuple):
    ts_start: int
    ts_end: int
    source: str
    pcm: np.ndarray  # int16 mono @ 16 kHz


# What Whisper emits when handed a room tone it has no words for. Only ever
# applied to a whole short transcript, never to a substring of a real utterance.
HALLUCINATIONS = {
    "you", "thank you", "thanks", "thank you.", "thanks.", "bye", "bye.",
    "thank you very much", "thank you for watching", "thanks for watching",
    "please subscribe", "you're welcome", "okay", "ok", "oh", "hmm", "mm",
    "yeah", "so", "the", "i", "uh", "um", ".", "..", "...", "!", "?",
}


_MIC_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def _own_mic_keys() -> set[str]:
    """Our own interpreter holds the mic too; it must not count as 'a call'."""
    import sys
    paths = {sys.executable, getattr(sys, "_base_executable", sys.executable)}
    return {p.replace("\\", "#").lower() for p in paths if p}


def other_app_using_mic() -> bool:
    """True if any app other than us has the microphone open right now.

    Windows records this per app (LastUsedTimeStop == 0 while in use) and it is
    what drives the taskbar mic icon. It catches browser calls such as Google
    Meet, which a list of meeting-app exe names would miss.

    ponytail: "someone else has the mic" is treated as "a call is on". Dictation
    or a voice recorder also qualifies. Add a meeting-app allowlist only if that
    turns out to matter.
    """
    import winreg
    own = _own_mic_keys()

    def scan(path: str) -> bool:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            return False
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    return False
                i += 1
                if sub == "NonPackaged":
                    if scan(path + "\\" + sub):
                        return True
                    continue
                if sub.lower() in own:
                    continue
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path + "\\" + sub) as k:
                        if winreg.QueryValueEx(k, "LastUsedTimeStop")[0] == 0:
                            return True
                except OSError:
                    continue

    return scan(_MIC_STORE)


def is_hallucination(text: str) -> bool:
    stripped = text.strip().lower()
    if not stripped:
        return True
    return stripped.rstrip(".!?,") in {h.rstrip(".!?,") for h in HALLUCINATIONS}


def to_mono16k(raw: bytes, in_rate: int, channels: int) -> np.ndarray:
    """Interleaved int16 at the device rate -> mono int16 at 16 kHz."""
    a = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        usable = (len(a) // channels) * channels
        a = a[:usable].reshape(-1, channels).mean(axis=1)
    a = a.astype(np.float32)
    if in_rate != RATE:
        if in_rate % RATE == 0:
            # Exact decimation (48k -> 16k is the common case). The group mean is
            # a box-filter anti-alias: crude, but VAD and Whisper both tolerate it.
            f = in_rate // RATE
            usable = (len(a) // f) * f
            a = a[:usable].reshape(-1, f).mean(axis=1)
        else:
            n = int(len(a) * RATE / in_rate)
            a = np.interp(np.linspace(0, len(a), n, endpoint=False),
                          np.arange(len(a)), a)
    return np.clip(a, -32768, 32767).astype(np.int16)


class VadChunker:
    """Accumulate speech, emit a segment once the talker stops.

    Keeps a short pre-roll so a segment does not open mid-syllable; without it
    the first word of every utterance is clipped and transcription suffers.
    """

    def __init__(self, source: str,
                 aggressiveness: int = config.VAD_AGGRESSIVENESS,
                 frame_ms: int = config.VAD_FRAME_MS,
                 silence_ms: int = config.VAD_SILENCE_MS,
                 min_ms: int = config.SEG_MIN_MS,
                 max_ms: int = config.SEG_MAX_MS,
                 preroll_frames: int = 5):
        import webrtcvad
        self.source = source
        self.vad = webrtcvad.Vad(aggressiveness)
        self.frame_len = int(RATE * frame_ms / 1000)
        self.frame_ms = frame_ms
        self.silence_frames = max(1, silence_ms // frame_ms)
        self.min_ms, self.max_ms = min_ms, max_ms
        self.preroll_frames = preroll_frames
        self._tail = np.zeros(0, dtype=np.int16)
        self._pre: list[np.ndarray] = []
        self._cur: list[np.ndarray] = []
        self._quiet = 0
        self._start_ms = 0

    def _emit(self, end_ms: int) -> Segment | None:
        if not self._cur:
            return None
        pcm = np.concatenate(self._cur)
        self._cur, self._quiet = [], 0
        if len(pcm) * 1000 // RATE < self.min_ms:
            return None
        return Segment(self._start_ms, end_ms, self.source, pcm)

    def push(self, pcm: np.ndarray, ts_ms: int) -> list[Segment]:
        """`ts_ms` is the wall-clock time of the first sample in `pcm`."""
        out: list[Segment] = []
        buf = np.concatenate([self._tail, pcm]) if self._tail.size else pcm
        offset_ms = ts_ms - (self._tail.size * 1000 // RATE)
        n = len(buf) // self.frame_len
        for i in range(n):
            frame = buf[i * self.frame_len:(i + 1) * self.frame_len]
            f_ms = offset_ms + i * self.frame_ms
            try:
                voiced = self.vad.is_speech(frame.tobytes(), RATE)
            except Exception:
                voiced = False
            if voiced:
                if not self._cur:
                    self._cur = list(self._pre)
                    self._start_ms = f_ms - len(self._pre) * self.frame_ms
                self._cur.append(frame)
                self._quiet = 0
            elif self._cur:
                self._cur.append(frame)
                self._quiet += 1
                if self._quiet >= self.silence_frames:
                    seg = self._emit(f_ms + self.frame_ms)
                    if seg:
                        out.append(seg)
            else:
                self._pre.append(frame)
                if len(self._pre) > self.preroll_frames:
                    self._pre.pop(0)
            if self._cur and (len(self._cur) * self.frame_ms) >= self.max_ms:
                seg = self._emit(f_ms + self.frame_ms)
                if seg:
                    out.append(seg)
        self._tail = buf[n * self.frame_len:]
        return out

    def flush(self) -> list[Segment]:
        seg = self._emit(int(time.time() * 1000))
        return [seg] if seg else []

    def reset(self) -> None:
        """Drop everything buffered, including a half-finished utterance."""
        self._tail = np.zeros(0, dtype=np.int16)
        self._pre, self._cur, self._quiet = [], [], 0


class Transcriber:
    """faster-whisper on the 4050. int8 keeps it well clear of the 6 GB ceiling."""

    def __init__(self, model_name: str = config.WHISPER_MODEL,
                 device: str = config.WHISPER_DEVICE,
                 compute: str = config.WHISPER_COMPUTE):
        from faster_whisper import WhisperModel
        self.name, self.device, self.compute = model_name, device, compute
        attempts = [(model_name, device, compute),
                    (config.WHISPER_FALLBACK_MODEL, device, compute),
                    (config.WHISPER_FALLBACK_MODEL, "cpu", "int8")]
        last = None
        for name, dev, comp in attempts:
            try:
                self.model = WhisperModel(name, device=dev, compute_type=comp)
                self.name, self.device, self.compute = name, dev, comp
                return
            except Exception as exc:
                last = exc
        raise RuntimeError(f"no Whisper model would load: {last}")

    def transcribe(self, pcm: np.ndarray) -> str:
        """Decode, then throw away what the model clearly invented.

        Three filters, cheapest first: an energy floor so near-silence is never
        decoded at all, then the decoder's own no-speech probability and average
        log-probability, then a blocklist for the stock hallucinations that slip
        past both. An empty string is the correct and common answer.
        """
        if pcm.size == 0:
            return ""
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        if rms < config.MIN_SEGMENT_RMS:
            return ""

        audio = pcm.astype(np.float32) / 32768.0
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                        vad_filter=False, condition_on_previous_text=False)
        kept = [s.text.strip() for s in segs
                if getattr(s, "no_speech_prob", 0.0) <= config.NO_SPEECH_MAX
                and getattr(s, "avg_logprob", 0.0) >= config.AVG_LOGPROB_MIN]
        text = " ".join(t for t in kept if t).strip()
        if is_hallucination(text):
            return ""
        return text


def input_devices(p) -> list[dict]:
    """WASAPI capture devices, loopbacks excluded."""
    import pyaudiowpatch as pa
    host = p.get_host_api_info_by_type(pa.paWASAPI)["index"]
    return [d for d in (p.get_device_info_by_index(i) for i in range(p.get_device_count()))
            if d["hostApi"] == host and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice")]


def pick_mic(p, want: str | None = config.MIC_DEVICE) -> dict:
    """`MIC_DEVICE` by name if set (e.g. "Microphone Array"), else the Windows default."""
    import pyaudiowpatch as pa
    if want:
        for d in input_devices(p):
            if want.lower() in d["name"].lower():
                return d
        raise RuntimeError(f"no input device matching MIC_DEVICE={want!r}")
    return p.get_device_info_by_index(p.get_host_api_info_by_type(pa.paWASAPI)["defaultInputDevice"])


class SilenceWatch:
    """Say so, once, when a source has heard nothing speech-loud for a long time.

    The first real hour recorded 66 minutes of a mic that delivered silence and
    nobody knew. Near-silence is normal (noise suppression gates a quiet room), so
    this can't call the mic broken; it only makes a long quiet stretch visible.
    """

    def __init__(self, after_s: float = config.SILENCE_WARN_S,
                 floor: float = config.MIN_SEGMENT_RMS):
        self.after_s, self.floor = after_s, floor
        self.quiet_since: float | None = None
        self.warned = False

    def feed(self, peak: float, now: float) -> str | None:
        if peak >= self.floor:
            back = self.warned
            self.quiet_since, self.warned = None, False
            return "sound is back" if back else None
        if self.quiet_since is None:
            self.quiet_since = now
        if not self.warned and now - self.quiet_since >= self.after_s:
            self.warned = True
            return (f"nothing speech-loud for {int(self.after_s // 60)} min. If you've been "
                    f"talking, check the input device (MIC_DEVICE in ambient/config.py)")
        return None


class _CaptureThread(threading.Thread):
    def __init__(self, pa, device: dict, source: str, sink: queue.Queue, stop: threading.Event,
                 paused: threading.Event):
        super().__init__(daemon=True, name=f"audio-{source}")
        self.pa, self.device, self.source, self.sink, self.stop = pa, device, source, sink, stop
        self.paused = paused
        self.error: str | None = None

    def run(self) -> None:
        rate = int(self.device["defaultSampleRate"])
        ch = min(2, int(self.device["maxInputChannels"]))
        block = int(rate * config.VAD_FRAME_MS / 1000) * 4
        chunker = VadChunker(self.source)
        watch = SilenceWatch()
        try:
            stream = self.pa.open(format=self.pa.get_format_from_width(2),  # int16
                                  channels=ch, rate=rate, input=True,
                                  frames_per_buffer=block,
                                  input_device_index=int(self.device["index"]))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            print(f"[audio] {self.source}: could not open {self.device['name']!r}: {self.error}")
            return
        print(f"[audio] {self.source}: listening on {self.device['name']!r}")
        try:
            while not self.stop.is_set():
                try:
                    raw = stream.read(block, exception_on_overflow=False)
                except Exception:
                    continue
                if self.paused.is_set():
                    # Keep draining the device so it doesn't overflow, but the
                    # audio goes nowhere -- and neither does the utterance that
                    # was in progress when the pause began.
                    chunker.reset()
                    continue
                ts = int(time.time() * 1000) - (block * 1000 // rate)
                pcm = to_mono16k(raw, rate, ch)
                note = watch.feed(float(np.abs(pcm).max()) if pcm.size else 0.0, time.monotonic())
                if note:
                    print(f"[audio] {self.source}: {note}")
                for seg in chunker.push(pcm, ts):
                    self.sink.put(seg)
            for seg in chunker.flush():
                self.sink.put(seg)
        finally:
            try:
                stream.stop_stream(); stream.close()
            except Exception:
                pass


class AudioPipeline:
    """Owns the capture threads and one transcription worker.

    `on_segment(ts_start, ts_end, source, text)` is called from the worker thread.
    """

    def __init__(self, on_segment: Callable[[int, int, str, str], None],
                 mic: bool = config.CAPTURE_MIC,
                 loopback: bool = config.CAPTURE_LOOPBACK):
        self.on_segment = on_segment
        self.want_mic, self.want_loopback = mic, loopback
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self.paused = threading.Event()   # set by the bus while a sensitive surface is focused
        self._threads: list[_CaptureThread] = []
        self._worker: threading.Thread | None = None
        self._pa = None
        self.transcriber: Transcriber | None = None
        self.errors: list[str] = []

    def _devices(self) -> list[tuple[dict, str]]:
        import pyaudiowpatch as pa
        out = []
        info = self._pa.get_host_api_info_by_type(pa.paWASAPI)
        if self.want_mic:
            try:
                out.append((pick_mic(self._pa), "mic"))
            except Exception as exc:
                self.errors.append(f"mic: {exc}")
        if self.want_loopback:
            try:
                spk = self._pa.get_device_info_by_index(info["defaultOutputDevice"])
                lb = next((d for d in self._pa.get_loopback_device_info_generator()
                           if spk["name"] in d["name"]), None)
                if lb:
                    out.append((lb, "loopback"))
                else:
                    self.errors.append("loopback: no device matching default output")
            except Exception as exc:
                self.errors.append(f"loopback: {exc}")
        return out

    def start(self) -> None:
        import pyaudiowpatch as pa
        self._pa = pa.PyAudio()
        self.transcriber = Transcriber()
        for dev, source in self._devices():
            t = _CaptureThread(self._pa, dev, source, self._q, self._stop, self.paused)
            t.start()
            self._threads.append(t)
        self._worker = threading.Thread(target=self._drain, daemon=True, name="transcribe")
        self._worker.start()

    def _drain(self) -> None:
        while not self._stop.is_set() or not self._q.empty():
            try:
                seg = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                text = self.transcriber.transcribe(seg.pcm)
                if text:
                    self.on_segment(seg.ts_start, seg.ts_end, seg.source, text)
            except Exception as exc:
                self.errors.append(f"transcribe: {type(exc).__name__}: {exc}")

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        if self._worker:
            self._worker.join(timeout=15)
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
