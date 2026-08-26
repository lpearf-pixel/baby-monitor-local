from __future__ import annotations

import json
import stat
from pathlib import Path

import numpy as np
import pytest

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings
from services.voice.audio_pump import PumpFrame
from services.voice.capture import UtteranceResult
from services.voice.challenge import EnrollmentChallenge
from services.voice.live_enrollment import (
    ENROLLMENT_FAILED,
    BoundedLivePcmCapture,
    EnrollmentFailure,
    EnrollmentRunReport,
    LiveEnrollmentCoordinator,
    VoiceProfileRegistry,
)
from services.voice.speaker import VoiceProfile
from services.voice.vad import VadResult


PROFILE_ID = "11111111-1111-4111-8111-111111111111"
PCM = np.full(16_000 * 3, 4_000, dtype="<i2").tobytes()


def profile() -> VoiceProfile:
    values = np.zeros(192, dtype=np.float64)
    values[0] = 1.0
    return VoiceProfile(
        profile_id=PROFILE_ID,
        model_version="speechbrain-ecapa-v1",
        embedding=tuple(float(value) for value in values),
        accept_threshold=0.80,
        uncertain_threshold=0.60,
        enrollment_quality="accepted",
    )


class Challenges:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.count = 0

    def issue(self) -> EnrollmentChallenge:
        self.count += 1
        return EnrollmentChallenge("a" * 32, f"小小，验证口令一二三{self.count}")

    def consume(self, _challenge_id: str, _transcript: str) -> bool:
        return self.accepted


class Asr:
    def transcribe(self, _pcm: bytes) -> object:
        return type("Result", (), {"text": "synthetic transcript"})()


class Enrollment:
    def __init__(self) -> None:
        self.samples: tuple[bytes, ...] | None = None

    def create(self, samples: tuple[bytes, ...]) -> VoiceProfile:
        self.samples = samples
        return profile()


class Registry:
    def __init__(self, existing: str | None = None, *, broken: bool = False) -> None:
        self.existing = existing
        self.broken = broken
        self.bound: tuple[str, str] | None = None

    def profile_id(self, _role: str) -> str | None:
        return self.existing

    def bind(self, role: str, profile_id: str) -> None:
        if self.broken:
            raise RuntimeError("private registry detail")
        self.bound = (role, profile_id)


class Store:
    def __init__(self) -> None:
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


def test_coordinator_consumes_three_challenges_before_binding_profile() -> None:
    prompts: list[str] = []
    enrollment = Enrollment()
    registry = Registry()
    store = Store()
    coordinator = LiveEnrollmentCoordinator(
        role="dad",
        capture=lambda phrase: prompts.append(phrase) or PCM,
        asr=Asr(),
        challenges=Challenges(),
        enrollment=enrollment,
        registry=registry,
        store=store,
    )

    report = coordinator.run()

    assert report == EnrollmentRunReport("dad", 3, "created", False)
    assert len(prompts) == 3
    assert enrollment.samples == (PCM, PCM, PCM)
    assert registry.bound == ("dad", PROFILE_ID)
    assert store.deleted is False
    assert "transcript" not in repr(report)


def test_challenge_failure_or_existing_role_creates_no_profile() -> None:
    enrollment = Enrollment()
    blocked_capture: list[str] = []
    with pytest.raises(EnrollmentFailure, match=f"^{ENROLLMENT_FAILED}$") as error:
        LiveEnrollmentCoordinator(
            role="mom",
            capture=lambda _phrase: PCM,
            asr=Asr(),
            challenges=Challenges(accepted=False),
            enrollment=enrollment,
            registry=Registry(),
            store=Store(),
        ).run()
    assert error.value.stage == "challenge"
    with pytest.raises(EnrollmentFailure, match=f"^{ENROLLMENT_FAILED}$") as error:
        LiveEnrollmentCoordinator(
            role="dad",
            capture=lambda phrase: blocked_capture.append(phrase) or PCM,
            asr=Asr(),
            challenges=Challenges(),
            enrollment=enrollment,
            registry=Registry(existing=PROFILE_ID),
            store=Store(),
        ).run()
    assert error.value.stage == "preflight"

    assert enrollment.samples is None
    assert blocked_capture == []


def test_registry_failure_deletes_the_just_created_profile() -> None:
    store = Store()
    with pytest.raises(ValueError, match=f"^{ENROLLMENT_FAILED}$"):
        LiveEnrollmentCoordinator(
            role="dad",
            capture=lambda _phrase: PCM,
            asr=Asr(),
            challenges=Challenges(),
            enrollment=Enrollment(),
            registry=Registry(broken=True),
            store=store,
        ).run()

    assert store.deleted is True


def test_registry_publishes_only_canonical_mode_0600_role_mapping(
    tmp_path: Path,
) -> None:
    path = tmp_path / "private/voice-profile-bindings.json"
    registry = VoiceProfileRegistry(path, boundary=tmp_path)

    registry.bind("dad", PROFILE_ID)

    assert registry.profile_id("dad") == PROFILE_ID
    assert registry.profile_id("mom") is None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="ascii")) == {
        "profiles": {"dad": PROFILE_ID},
        "schemaVersion": 1,
    }


class Pump:
    def __init__(self, frames: list[PumpFrame]) -> None:
        self.frames = frames
        self.warmed = False
        self.closed = False

    def warm_up(self, cancelled: object) -> bool:
        assert cancelled.is_set() is False
        self.warmed = True
        return True

    def read_frame(self) -> PumpFrame:
        return self.frames.pop(0)

    def close(self) -> None:
        self.closed = True


class Vad:
    def __init__(self) -> None:
        self.observed: list[bytes] = []
        self.reset_count = 0
        self.closed = False

    def observe(self, pcm: bytes) -> VadResult:
        self.observed.append(pcm)
        return VadResult(True, 0.9)

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Collector:
    def __init__(self) -> None:
        self.pushed: list[bytes] = []
        self.reset_count = 0
        self.closed = False

    def push(self, pcm: bytes, _vad: VadResult) -> UtteranceResult | None:
        self.pushed.append(pcm)
        if len(self.pushed) == 2:
            return UtteranceResult(b"complete utterance", "terminal_silence")
        return None

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


def test_bounded_capture_drains_countdown_then_returns_one_vad_utterance() -> None:
    frames = [PumpFrame(b"d" * 3_200)] * 20 + [
        PumpFrame(b"speech-1" * 400),
        PumpFrame(b"speech-2" * 400),
    ]
    pump = Pump(frames)
    vad = Vad()
    collector = Collector()
    output: list[str] = []
    capture = BoundedLivePcmCapture(
        AudioSettings(),
        pump_factory=lambda _settings: pump,
        vad_factory=lambda: vad,
        collector_factory=lambda: collector,
    )

    pcm = capture.capture(countdown_seconds=2, printer=output.append)

    assert pcm == b"complete utterance"
    assert output == [
        "capture_starts_in_seconds=2",
        "capture_starts_in_seconds=1",
        "capture_now=true",
    ]
    assert pump.warmed is True
    assert pump.frames == []
    assert vad.observed == [b"speech-1" * 400, b"speech-2" * 400]
    assert pump.closed is True
    assert vad.closed is True
    assert collector.closed is True


def test_bounded_capture_source_failure_during_countdown_is_closed() -> None:
    pump = Pump([PumpFrame(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)])
    vad = Vad()
    collector = Collector()
    with pytest.raises(ValueError, match=f"^{ENROLLMENT_FAILED}$"):
        BoundedLivePcmCapture(
            AudioSettings(),
            pump_factory=lambda _settings: pump,
            vad_factory=lambda: vad,
            collector_factory=lambda: collector,
        ).capture(countdown_seconds=1, printer=lambda _line: None)

    assert pump.closed is True
    assert vad.closed is True
    assert collector.closed is True


def test_registry_refuses_symlinked_ancestor_without_external_write(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(outside, target_is_directory=True)
    registry = VoiceProfileRegistry(
        runtime / "private/voice-profile-bindings.json",
        boundary=tmp_path,
    )

    with pytest.raises(ValueError, match=f"^{ENROLLMENT_FAILED}$"):
        registry.bind("dad", PROFILE_ID)

    assert list(outside.iterdir()) == []
