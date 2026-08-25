"""Production composition for the isolated memory-only Voice listener."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol

from packages.contracts.settings import AppSettings
from services.audio.source import FixedAudioDecoder
from services.voice.artifacts import voice_artifact_spec
from services.voice.audio_pump import ExactFrameAudioPump
from services.voice.capture import UtteranceCollector
from services.voice.listen_only import ListenOnlyController, ListenOnlyOutcome
from services.voice.paraformer import ParaformerProcess
from services.voice.silero_runtime import StreamingSileroVad
from services.voice.tts import BoundedCommandRunner, FixedVoiceSynthesizer
from services.voice.worker import VoiceStatusWriter


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class PlaybackDucker:
    """Drain and discard camera input while the i9 plays a fixed response."""

    def __init__(self, *, pump: object, vad: object, collector: object) -> None:
        self._pump = pump
        self._vad = vad
        self._collector = collector
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def pause(self) -> None:
        self.resume()
        self._collector.reset()
        self._vad.reset()
        self._pump.begin_duck()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._drain,
            name="voice-playback-drain",
            daemon=True,
        )
        self._thread.start()

    def resume(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.25)
        self._pump.end_duck()
        self._collector.reset()
        self._vad.reset()

    def close(self) -> None:
        self.resume()

    def _drain(self) -> None:
        while not self._stop.is_set():
            try:
                self._pump.read_frame()
            except Exception:
                self._stop.wait(0.05)


class ListenOnlyVoiceWorker:
    """Drive the fixed audio/VAD/ASR/wake loop without a care-write boundary."""

    def __init__(
        self,
        *,
        pump: object,
        vad: object,
        collector: object,
        controller: object,
        asr_closer: object,
        status_writer: object,
        ducker_closer: object | None = None,
        clock=None,
        monotonic_ns=time.monotonic_ns,
    ) -> None:
        self._pump = pump
        self._vad = vad
        self._collector = collector
        self._controller = controller
        self._asr_closer = asr_closer
        self._status_writer = status_writer
        self._ducker_closer = ducker_closer
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._monotonic_ns = monotonic_ns
        self._processed_count = 0
        self._closed = False

    def step(self, cancelled: StopEvent) -> None:
        started_ns = self._monotonic_ns()
        try:
            expired = self._controller.expire(started_ns)
            if expired.reason == "listen_only_timeout":
                self._write("healthy", expired.reason, None)
            frame = self._pump.read_frame()
            if frame.failure_reason is not None:
                self._reset_capture()
                self._write("degraded", "voice_audio_unavailable", None)
                return
            if frame.dropped:
                return
            vad = self._vad.observe(frame.pcm)
            if vad.reason is not None:
                self._reset_capture()
                self._write("degraded", "voice_model_unavailable", None)
                return
            if vad.speech:
                self._controller.on_speech_started(started_ns)
            utterance = self._collector.push(frame.pcm, vad)
            if utterance is None:
                self._write("healthy", "listen_only_idle", None)
                return
            outcome: ListenOnlyOutcome = self._controller.handle(
                utterance.pcm, cancelled
            )
            self._vad.reset()
            latency_ms = min(
                30_000,
                max(0, (self._monotonic_ns() - started_ns) // 1_000_000),
            )
            if outcome.response_code is not None:
                self._processed_count += 1
            state = (
                "degraded"
                if outcome.reason
                in {"voice_model_unavailable", "voice_output_unavailable"}
                else "healthy"
            )
            self._write(state, outcome.reason, latency_ms)
        except Exception:
            self._reset_capture()
            self._write("degraded", "voice_worker_unavailable", None)

    def run(self, stop_event: StopEvent) -> None:
        try:
            while not stop_event.is_set():
                if self._pump.warm_up(stop_event):
                    self._write("healthy", "listen_only_idle", None)
                    break
                self._reset_capture()
                self._write("degraded", "voice_audio_unavailable", None)
                if stop_event.wait(1.0):
                    return
            while not stop_event.is_set():
                self.step(stop_event)
                stop_event.wait(0.01)
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ducker_closer is not None:
            self._ducker_closer.close()
        self._collector.close()
        self._vad.close()
        self._asr_closer.close()
        self._pump.close()

    def _reset_capture(self) -> None:
        self._collector.reset()
        self._vad.reset()
        self._controller.reset()

    def _write(self, state: str, reason: str, latency_ms: int | None) -> None:
        try:
            self._status_writer.write(
                mode="listen_only",
                worker_state=state,
                reason=reason,
                processed_count=self._processed_count,
                last_latency_ms=latency_ms,
            )
        except Exception:
            pass


def build_listen_only_worker(
    settings: AppSettings, project_root: Path
) -> ListenOnlyVoiceWorker:
    """Build only the fixed decoder, VAD, ASR, wake controller, and local TTS."""

    root = Path(project_root).resolve(strict=True)
    voice = settings.voice_care
    if not voice.listen_only_enabled or voice.enabled:
        raise ValueError("voice_runtime_unavailable")
    pump = None
    vad = None
    collector = None
    asr = None
    ducker = None
    try:
        pump = ExactFrameAudioPump(FixedAudioDecoder(settings.audio))
        vad = StreamingSileroVad(
            voice_artifact_spec(voice, "silero-vad-v6.2"),
            project_root=root,
        )
        collector = UtteranceCollector(voice)
        asr = ParaformerProcess(
            voice_artifact_spec(
                voice, "sherpa-onnx-paraformer-zh-2023-09-14"
            ),
            project_root=root,
        )
        ducker = PlaybackDucker(pump=pump, vad=vad, collector=collector)
        synthesizer = FixedVoiceSynthesizer(
            runner=BoundedCommandRunner(),
            ducker=ducker,
        )
        controller = ListenOnlyController(asr=asr, synthesizer=synthesizer)
        return ListenOnlyVoiceWorker(
            pump=pump,
            vad=vad,
            collector=collector,
            controller=controller,
            asr_closer=asr,
            status_writer=VoiceStatusWriter(root / "runtime/status/voice.json"),
            ducker_closer=ducker,
        )
    except Exception:
        if ducker is not None:
            ducker.close()
        if collector is not None:
            collector.close()
        if vad is not None:
            vad.close()
        if asr is not None:
            asr.close()
        if pump is not None:
            pump.close()
        raise ValueError("voice_runtime_unavailable") from None


__all__ = [
    "ListenOnlyVoiceWorker",
    "PlaybackDucker",
    "build_listen_only_worker",
]
