from __future__ import annotations

import threading
import json
import hashlib
from pathlib import Path
from datetime import UTC, datetime

import pytest

from packages.contracts.audio import AudioFailureReason
from services.voice.audio_pump import PumpFrame
from services.voice.capture import UtteranceResult
from services.voice.listen_only import ListenOnlyOutcome
from packages.contracts.settings import VoiceCareSettings
from packages.monitoring.go2rtc_build import BuildMetadata
from services.voice.camera_reply import (
    CameraReplyAcceptance,
    CameraReplyCode,
    CameraReplyEvidence,
)
from services.voice.listen_only_runtime import (
    ListenOnlyVoiceWorker,
    PlaybackDucker,
    camera_reply_readiness,
)
from services.voice.vad import VadResult


class Pump:
    def __init__(self, frames: list[PumpFrame]) -> None:
        self.frames = frames
        self.ducked = False
        self.closed = False
        self.read_count = 0

    def warm_up(self, _cancelled) -> bool:
        return True

    def read_frame(self) -> PumpFrame:
        self.read_count += 1
        return self.frames.pop(0) if self.frames else PumpFrame(b"", dropped=True)

    def begin_duck(self) -> None:
        self.ducked = True

    def end_duck(self) -> None:
        self.ducked = False

    def close(self) -> None:
        self.closed = True


class Vad:
    def __init__(self, result: VadResult) -> None:
        self.result = result
        self.reset_count = 0
        self.closed = False

    def observe(self, _frame: bytes) -> VadResult:
        return self.result

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Collector:
    def __init__(self, result: UtteranceResult | None) -> None:
        self.result = result
        self.reset_count = 0
        self.closed = False

    def push(self, _frame: bytes, _vad: VadResult):
        result, self.result = self.result, None
        return result

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Controller:
    def __init__(
        self,
        outcome: ListenOnlyOutcome,
        *,
        expired: ListenOnlyOutcome | None = None,
    ) -> None:
        self.outcome = outcome
        self.expired = expired or ListenOnlyOutcome("listen_only_idle", None, "idle")
        self.started: list[int] = []
        self.handled: list[bytes] = []
        self.replayed: list[bool] = []
        self.reset_count = 0

    def expire(self, _now_ns: int) -> ListenOnlyOutcome:
        return self.expired

    def on_speech_started(self, now_ns: int) -> bool:
        self.started.append(now_ns)
        return True

    def handle(
        self, pcm: bytes, _cancelled, *, from_replay: bool = False
    ) -> ListenOnlyOutcome:
        self.handled.append(pcm)
        self.replayed.append(from_replay)
        return self.outcome

    def reset(self) -> None:
        self.reset_count += 1


class Status:
    def __init__(self) -> None:
        self.values: list[dict[str, object]] = []

    def write(self, **value: object) -> None:
        self.values.append(value)


class AsrCloser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_worker_routes_one_completed_utterance_to_listen_only_controller() -> None:
    pump = Pump([PumpFrame(b"p" * 3_200)])
    vad = Vad(VadResult(True, 0.9))
    collector = Collector(UtteranceResult(b"u" * 32_000, "terminal_silence"))
    controller = Controller(
        ListenOnlyOutcome("listen_only_acknowledged", "listen_only_received", "idle")
    )
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    assert controller.started == [1_000_000_000]
    assert controller.handled == [b"u" * 32_000]
    assert controller.replayed == [False]
    assert vad.reset_count == 1
    assert status.values[-1] == {
        "mode": "listen_only",
        "worker_state": "healthy",
        "reason": "listen_only_acknowledged",
        "processed_count": 1,
        "last_latency_ms": 80,
        "transition_counts": {
            "armed_timeouts": 0,
            "ignored_followups": 0,
            "ignored_far": 0,
            "ignored_near_reply_echo": 0,
            "ignored_near_start": 0,
            "listen_only_action_rejected": 0,
            "listen_only_burping_exact": 0,
            "listen_only_diaper_exact": 0,
            "listen_only_feeding_corrected": 0,
            "listen_only_feeding_exact": 0,
            "listen_only_medication_candidate": 0,
            "output_failures": 0,
            "replay_frames": 0,
            "replay_ignored": 0,
            "replay_utterances": 0,
            "reply_echo_ignored": 0,
            "utterances": 1,
            "vad_speech_frames": 1,
        },
    }


def test_worker_preserves_replay_provenance_for_completed_utterance() -> None:
    controller = Controller(
        ListenOnlyOutcome("listen_only_acknowledged", "listen_only_received", "idle")
    )
    worker = ListenOnlyVoiceWorker(
        pump=Pump([PumpFrame(b"p" * 3_200, replayed=True)]),
        vad=Vad(VadResult(True, 0.9)),
        collector=Collector(UtteranceResult(b"u" * 32_000, "terminal_silence")),
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=Status(),
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    assert controller.replayed == [True]


def test_worker_publishes_only_bounded_replay_transition_counts() -> None:
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=Pump([PumpFrame(b"p" * 3_200, replayed=True)]),
        vad=Vad(VadResult(True, 0.9)),
        collector=Collector(UtteranceResult(b"u" * 32_000, "terminal_silence")),
        controller=Controller(
            ListenOnlyOutcome("listen_only_replay_ignored", None, "armed")
        ),
        asr_closer=AsrCloser(),
        status_writer=status,
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    assert status.values[-1]["transition_counts"] == {
        "armed_timeouts": 0,
        "ignored_followups": 0,
        "ignored_far": 0,
        "ignored_near_reply_echo": 0,
        "ignored_near_start": 0,
        "listen_only_action_rejected": 0,
        "listen_only_burping_exact": 0,
        "listen_only_diaper_exact": 0,
        "listen_only_feeding_corrected": 0,
        "listen_only_feeding_exact": 0,
        "listen_only_medication_candidate": 0,
        "output_failures": 0,
        "replay_frames": 1,
        "replay_ignored": 1,
        "replay_utterances": 1,
        "reply_echo_ignored": 0,
        "utterances": 1,
        "vad_speech_frames": 1,
    }


@pytest.mark.parametrize(
    ("action_code", "match_kind", "counter"),
    [
        ("feeding_command", "exact", "listen_only_feeding_exact"),
        ("feeding_command", "corrected", "listen_only_feeding_corrected"),
        ("diaper_change_start", "exact", "listen_only_diaper_exact"),
        ("burping_start", "exact", "listen_only_burping_exact"),
        (
            "medication_start_candidate",
            "high_risk_candidate",
            "listen_only_medication_candidate",
        ),
    ],
)
def test_worker_counts_one_fixed_terminal_action_without_transcript(
    action_code: str,
    match_kind: str,
    counter: str,
) -> None:
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=Pump([PumpFrame(b"p" * 3_200)]),
        vad=Vad(VadResult(True, 0.9)),
        collector=Collector(UtteranceResult(b"u" * 32_000, "terminal_silence")),
        controller=Controller(
            ListenOnlyOutcome(
                "listen_only_high_risk_candidate"
                if match_kind == "high_risk_candidate"
                else "listen_only_acknowledged",
                None if match_kind == "high_risk_candidate" else "listen_only_received",
                "idle",
                action_code=action_code,
                match_kind=match_kind,
            )
        ),
        asr_closer=AsrCloser(),
        status_writer=status,
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    counts = status.values[-1]["transition_counts"]
    action_keys = {
        "listen_only_feeding_exact",
        "listen_only_feeding_corrected",
        "listen_only_diaper_exact",
        "listen_only_burping_exact",
        "listen_only_medication_candidate",
    }
    assert counts[counter] == 1
    assert sum(counts[key] for key in action_keys) == 1


def test_worker_counts_armed_rejection_once_without_action_metadata() -> None:
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=Pump([PumpFrame(b"p" * 3_200)]),
        vad=Vad(VadResult(True, 0.9)),
        collector=Collector(UtteranceResult(b"u" * 32_000, "terminal_silence")),
        controller=Controller(
            ListenOnlyOutcome("listen_only_followup_far", None, "idle"),
            expired=ListenOnlyOutcome("listen_only_armed", None, "armed"),
        ),
        asr_closer=AsrCloser(),
        status_writer=status,
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    assert status.values[-1]["transition_counts"]["listen_only_action_rejected"] == 1


def test_worker_source_failure_resets_only_voice_state_and_fails_closed() -> None:
    pump = Pump([PumpFrame(b"", AudioFailureReason.AUDIO_STALE)])
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    controller = Controller(ListenOnlyOutcome("listen_only_idle", None, "idle"))
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
    )

    worker.step(threading.Event())

    assert vad.reset_count == 1
    assert collector.reset_count == 1
    assert controller.reset_count == 1
    assert status.values[-1]["reason"] == "voice_audio_unavailable"


def test_worker_output_failure_resets_collector_controller_and_remains_runnable() -> None:
    pump = Pump(
        [PumpFrame(b"p" * 3_200), PumpFrame(b"", dropped=True)]
    )
    vad = Vad(VadResult(True, 0.9))
    collector = Collector(UtteranceResult(b"u" * 32_000, "terminal_silence"))
    controller = Controller(
        ListenOnlyOutcome("voice_output_unavailable", None, "idle")
    )
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
    )

    worker.step(threading.Event())

    assert vad.reset_count == 1
    assert collector.reset_count == 1
    assert controller.reset_count == 1
    assert status.values[-1]["reason"] == "voice_output_unavailable"

    worker.step(threading.Event())
    assert pump.read_count == 2


def test_worker_keeps_armed_status_visible_while_waiting_for_followup() -> None:
    pump = Pump([PumpFrame(b"p" * 3_200)])
    controller = Controller(
        ListenOnlyOutcome("listen_only_ignored", None, "idle"),
        expired=ListenOnlyOutcome("listen_only_armed", None, "armed"),
    )
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=Vad(VadResult(False, 0.1)),
        collector=Collector(None),
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
    )

    worker.step(threading.Event())

    assert status.values[-1]["reason"] == "listen_only_armed"


def test_playback_ducker_drains_audio_and_resets_capture_state() -> None:
    pump = Pump([PumpFrame(b"", dropped=True)] * 100)
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    ducker = PlaybackDucker(pump=pump, vad=vad, collector=collector)

    ducker.pause()
    assert pump.ducked is True
    assert threading.Event().wait(0.02) is False
    ducker.resume()

    assert pump.read_count > 0
    assert pump.ducked is False
    assert vad.reset_count >= 2
    assert collector.reset_count >= 2


def test_worker_close_settles_all_owned_voice_resources() -> None:
    pump = Pump([])
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    controller = Controller(ListenOnlyOutcome("listen_only_idle", None, "idle"))
    asr = AsrCloser()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=asr,
        status_writer=Status(),
    )

    worker.close()
    worker.close()

    assert pump.closed is True
    assert vad.closed is True
    assert collector.closed is True
    assert asr.closed is True


def _listen_settings(*, camera: bool) -> VoiceCareSettings:
    return VoiceCareSettings(
        listen_only_enabled=True,
        camera_reply_enabled=camera,
        silero_vad_manifest_sha256="1" * 64,
        paraformer_zh_manifest_sha256="2" * 64,
    )


def _current_build(root: Path) -> BuildMetadata:
    patch = root / "patches/go2rtc-macos-hybrid-hd.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"patch")
    binary = root / ".local/bin/go2rtc"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    binary.chmod(0o755)
    metadata = BuildMetadata(
        upstream_commit="b465651a94c1f637d566a8c660b4fad102b35153",
        go_version="go1.24.13",
        patch_sha256=hashlib.sha256(b"patch").hexdigest(),
        binary_sha256=hashlib.sha256(b"binary").hexdigest(),
        build_time="2026-08-26T00:00:00+00:00",
        platform="darwin/amd64",
    )
    build = root / "runtime/build"
    build.mkdir(parents=True, mode=0o700)
    (build / "go2rtc.json").write_text(
        json.dumps(metadata.as_dict()), encoding="ascii"
    )
    return metadata


def test_camera_reply_readiness_requires_flag_and_current_marker(
    tmp_path: Path,
) -> None:
    metadata = _current_build(tmp_path)

    assert camera_reply_readiness(_listen_settings(camera=False), tmp_path) is (
        CameraReplyCode.DISABLED
    )
    assert camera_reply_readiness(_listen_settings(camera=True), tmp_path) is (
        CameraReplyCode.NOT_PROVEN
    )

    evidence = CameraReplyEvidence(
        source_ready=True,
        video_ready=True,
        incoming_audio_ready=True,
        sendonly_audio_ready=True,
        protocol="cs2+udp",
        video_codec="HEVC",
        incoming_audio_codec="OPUS",
        sendonly_audio_codec="OPUS",
        speaker_session_generation=1,
        speaker_start_requests=1,
        speaker_start_responses=1,
        speaker_stop_commands=1,
        speaker_audio_packets=1,
        speaker_audio_bytes=100,
        producer_id=41,
        producer_generation=1,
    )
    assert CameraReplyAcceptance.publish(tmp_path, metadata, evidence) is True
    assert camera_reply_readiness(_listen_settings(camera=True), tmp_path) is (
        CameraReplyCode.READY
    )

    binary = tmp_path / ".local/bin/go2rtc"
    binary.write_bytes(b"changed")
    assert camera_reply_readiness(_listen_settings(camera=True), tmp_path) is (
        CameraReplyCode.NOT_PROVEN
    )
