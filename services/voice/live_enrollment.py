"""Memory-only adult enrollment coordination and private role registry."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from packages.contracts.settings import AudioSettings
from services.audio.source import DecoderRead, FixedAudioDecoder
from services.voice.challenge import EnrollmentChallenge
from services.voice.speaker import VoiceProfile


ENROLLMENT_FAILED = "voice_enrollment_failed"
CAPTURE_SECONDS = 5
CAPTURE_TIMEOUT_SECONDS = 10.0
_MAX_REGISTRY_BYTES = 4_096
_ROLES = frozenset({"dad", "mom"})
_FAILURE_STAGES = frozenset(
    {"preflight", "capture", "asr", "challenge", "speaker", "storage"}
)


class EnrollmentFailure(ValueError):
    """One redacted, allowlisted enrollment failure stage."""

    def __init__(self, stage: str) -> None:
        if stage not in _FAILURE_STAGES:
            stage = "preflight"
        self.stage = stage
        super().__init__(ENROLLMENT_FAILED)


class _Asr(Protocol):
    def transcribe(self, pcm: bytes) -> object: ...


class _Challenges(Protocol):
    def issue(self) -> EnrollmentChallenge: ...

    def consume(self, challenge_id: str, transcript: str) -> bool: ...


class _Enrollment(Protocol):
    def create(self, samples: tuple[bytes, ...]) -> VoiceProfile: ...


class _Registry(Protocol):
    def profile_id(self, role: str) -> str | None: ...

    def bind(self, role: str, profile_id: str) -> None: ...


class _Store(Protocol):
    def delete(self) -> None: ...


class _Decoder(Protocol):
    def read(
        self, maximum: int, *, timeout_seconds: float | None = None
    ) -> DecoderRead: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class EnrollmentRunReport:
    role: Literal["dad", "mom"]
    sample_count: int
    profile_state: Literal["created"]
    raw_audio_persisted: Literal[False]


class LiveEnrollmentCoordinator:
    """Require three fresh spoken challenges before binding one local profile."""

    def __init__(
        self,
        *,
        role: str,
        capture: Callable[[str], bytes],
        asr: _Asr,
        challenges: _Challenges,
        enrollment: _Enrollment,
        registry: _Registry,
        store: _Store,
    ) -> None:
        self._role = role
        self._capture = capture
        self._asr = asr
        self._challenges = challenges
        self._enrollment = enrollment
        self._registry = registry
        self._store = store

    def run(self) -> EnrollmentRunReport:
        samples: list[bytes] = []
        profile_created = False
        stage = "preflight"
        try:
            role = _validated_role(self._role)
            if self._registry.profile_id(role) is not None:
                raise ValueError(ENROLLMENT_FAILED)
            for _index in range(3):
                stage = "challenge"
                challenge = self._challenges.issue()
                stage = "capture"
                pcm = self._capture(challenge.phrase)
                if type(pcm) is not bytes or not pcm:
                    raise ValueError(ENROLLMENT_FAILED)
                stage = "asr"
                transcript = getattr(self._asr.transcribe(pcm), "text")
                if type(transcript) is not str:
                    raise ValueError(ENROLLMENT_FAILED)
                stage = "challenge"
                if not self._challenges.consume(challenge.challenge_id, transcript):
                    raise ValueError(ENROLLMENT_FAILED)
                samples.append(pcm)
            stage = "speaker"
            profile = self._enrollment.create(tuple(samples))
            profile_created = True
            stage = "storage"
            self._registry.bind(role, profile.profile_id)
            return EnrollmentRunReport(role, 3, "created", False)
        except Exception:
            if profile_created:
                try:
                    self._store.delete()
                except Exception:
                    pass
            raise EnrollmentFailure(stage) from None
        finally:
            samples.clear()


class BoundedLivePcmCapture:
    """Receive one exact five-second PCM sample without a media file."""

    def __init__(
        self,
        settings: AudioSettings,
        *,
        decoder_factory: Callable[[AudioSettings], _Decoder] = FixedAudioDecoder,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._decoder_factory = decoder_factory
        self._clock = clock

    def capture(self) -> bytes:
        buffer = bytearray()
        decoder: _Decoder | None = None
        try:
            target = (
                self._settings.sample_rate_hz
                * self._settings.channels
                * self._settings.sample_width_bytes
                * CAPTURE_SECONDS
            )
            if target != 160_000:
                raise ValueError(ENROLLMENT_FAILED)
            decoder = self._decoder_factory(self._settings)
            started = float(self._clock())
            while len(buffer) < target:
                if float(self._clock()) - started >= CAPTURE_TIMEOUT_SECONDS:
                    raise ValueError(ENROLLMENT_FAILED)
                remaining = target - len(buffer)
                remaining_seconds = CAPTURE_TIMEOUT_SECONDS - (
                    float(self._clock()) - started
                )
                if remaining_seconds <= 0:
                    raise ValueError(ENROLLMENT_FAILED)
                result = decoder.read(
                    remaining, timeout_seconds=min(10.0, remaining_seconds)
                )
                if (
                    not isinstance(result, DecoderRead)
                    or result.failure_reason is not None
                    or type(result.pcm) is not bytes
                    or not result.pcm
                    or len(result.pcm) > remaining
                    or len(result.pcm) % self._settings.sample_width_bytes
                ):
                    raise ValueError(ENROLLMENT_FAILED)
                buffer.extend(result.pcm)
            return bytes(buffer)
        except Exception:
            raise ValueError(ENROLLMENT_FAILED) from None
        finally:
            for index in range(len(buffer)):
                buffer[index] = 0
            buffer.clear()
            if decoder is not None:
                decoder.close()


class VoiceProfileRegistry:
    """Store only Dad/Mom to opaque-profile mappings in one private canonical file."""

    def __init__(self, path: Path, *, boundary: Path) -> None:
        self._path = path
        self._boundary = boundary.resolve(strict=True)
        if self._boundary.is_symlink() or not self._boundary.is_dir():
            raise ValueError(ENROLLMENT_FAILED)

    def profile_id(self, role: str) -> str | None:
        checked = _validated_role(role)
        return self._read().get(checked)

    def bind(self, role: str, profile_id: str) -> None:
        try:
            checked_role = _validated_role(role)
            checked_id = _canonical_profile_id(profile_id)
            profiles = self._read()
            if checked_role in profiles or checked_id in profiles.values():
                raise ValueError(ENROLLMENT_FAILED)
            profiles[checked_role] = checked_id
            self._publish(profiles)
        except Exception:
            raise ValueError(ENROLLMENT_FAILED) from None

    def _read(self) -> dict[str, str]:
        self._validate_boundary()
        if not self._path.exists() and not self._path.is_symlink():
            return {}
        descriptor = -1
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
            value = os.fstat(descriptor)
            payload = os.read(descriptor, _MAX_REGISTRY_BYTES + 1)
            if (
                not stat.S_ISREG(value.st_mode)
                or stat.S_IMODE(value.st_mode) != 0o600
                or not 0 < value.st_size <= _MAX_REGISTRY_BYTES
                or len(payload) != value.st_size
            ):
                raise ValueError(ENROLLMENT_FAILED)
            parsed = json.loads(payload.decode("ascii"))
            if (
                not isinstance(parsed, dict)
                or set(parsed) != {"profiles", "schemaVersion"}
                or parsed["schemaVersion"] != 1
                or not isinstance(parsed["profiles"], dict)
                or set(parsed["profiles"]) - _ROLES
                or payload != _canonical_registry(parsed["profiles"])
            ):
                raise ValueError(ENROLLMENT_FAILED)
            profiles = {
                _validated_role(role): _canonical_profile_id(profile_id)
                for role, profile_id in parsed["profiles"].items()
            }
            if len(set(profiles.values())) != len(profiles):
                raise ValueError(ENROLLMENT_FAILED)
            return profiles
        except Exception:
            raise ValueError(ENROLLMENT_FAILED) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _publish(self, profiles: dict[str, str]) -> None:
        self._validate_boundary()
        parent = self._path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise ValueError(ENROLLMENT_FAILED)
        parent.chmod(0o700)
        if self._path.is_symlink():
            raise ValueError(ENROLLMENT_FAILED)
        if self._path.exists():
            value = self._path.lstat()
            if not stat.S_ISREG(value.st_mode) or stat.S_IMODE(value.st_mode) != 0o600:
                raise ValueError(ENROLLMENT_FAILED)
        payload = _canonical_registry(profiles)
        descriptor, temporary = tempfile.mkstemp(prefix=".voice-bindings-", dir=parent)
        temporary_path = Path(temporary)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                descriptor = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary_path.unlink(missing_ok=True)

    def _validate_boundary(self) -> None:
        try:
            relative = self._path.relative_to(self._boundary)
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(ENROLLMENT_FAILED)
            current = self._boundary
            for part in relative.parts[:-1]:
                current = current / part
                if current.is_symlink() or (
                    current.exists() and not current.is_dir()
                ):
                    raise ValueError(ENROLLMENT_FAILED)
        except Exception:
            raise ValueError(ENROLLMENT_FAILED) from None


def _canonical_registry(profiles: dict[str, str]) -> bytes:
    value = {"profiles": profiles, "schemaVersion": 1}
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )


def _validated_role(role: str) -> Literal["dad", "mom"]:
    if role == "dad":
        return "dad"
    if role == "mom":
        return "mom"
    raise ValueError(ENROLLMENT_FAILED)


def _canonical_profile_id(profile_id: object) -> str:
    try:
        canonical = str(UUID(str(profile_id)))
    except Exception:
        raise ValueError(ENROLLMENT_FAILED) from None
    if type(profile_id) is not str or canonical != profile_id:
        raise ValueError(ENROLLMENT_FAILED)
    return canonical


__all__ = [
    "BoundedLivePcmCapture",
    "ENROLLMENT_FAILED",
    "EnrollmentFailure",
    "EnrollmentRunReport",
    "LiveEnrollmentCoordinator",
    "VoiceProfileRegistry",
]
