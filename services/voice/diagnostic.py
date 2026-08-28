"""Private, bounded artifacts for an explicitly supervised Voice diagnostic."""

from __future__ import annotations

import json
import math
import os
import queue
import re
import stat
import tempfile
import threading
import unicodedata
import wave
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal


DIAGNOSTIC_LIFETIME_SECONDS = 1_800
DIAGNOSTIC_MAX_UTTERANCES = 50
DIAGNOSTIC_MAX_BYTES = 16_777_216
DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS = 256
DIAGNOSTIC_QUEUE_CAPACITY = 2
DIAGNOSTIC_SETTLEMENT_SECONDS = 5.0

VOICE_DIAGNOSTIC_UNAVAILABLE = "voice_diagnostic_unavailable"
_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
_ARTIFACT_NAME = re.compile(r"^(?P<sequence>[0-9]{6})\.(?:wav|json)$")
_MAX_METADATA_BYTES = 16_384
_MAX_PCM_BYTES = 16_000 * 2 * 8
_ACTION_CODES = frozenset(
    {
        "feeding_command",
        "diaper_change_start",
        "diaper_change_complete",
        "burping_start",
        "burping_complete",
        "medication_start_candidate",
        "medication_complete_candidate",
    }
)
_MATCH_KINDS = frozenset({"exact", "corrected", "high_risk_candidate"})
_OUTCOME_REASONS = frozenset(
    {
        "listen_only_idle",
        "listen_only_ignored",
        "listen_only_armed",
        "listen_only_acknowledged",
        "listen_only_acknowledged_corrected",
        "listen_only_high_risk_candidate",
        "listen_only_timeout",
        "listen_only_replay_ignored",
        "listen_only_reply_echo_ignored",
        "listen_only_followup_near_start",
        "listen_only_followup_near_reply_echo",
        "listen_only_followup_far",
        "voice_model_unavailable",
        "voice_output_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class DiagnosticSession:
    session_id: str
    created_epoch: float
    expires_epoch: float
    complete_count: int
    complete_bytes: int
    next_sequence: int
    _session_root: Path = field(repr=False)

    def __post_init__(self) -> None:
        if (
            _SESSION_ID.fullmatch(self.session_id) is None
            or not _finite_number(self.created_epoch)
            or not _finite_number(self.expires_epoch)
            or self.expires_epoch - self.created_epoch
            != DIAGNOSTIC_LIFETIME_SECONDS
            or type(self.complete_count) is not int
            or not 0 <= self.complete_count <= DIAGNOSTIC_MAX_UTTERANCES
            or type(self.complete_bytes) is not int
            or not 0 <= self.complete_bytes <= DIAGNOSTIC_MAX_BYTES
            or type(self.next_sequence) is not int
            or not 1 <= self.next_sequence <= DIAGNOSTIC_MAX_UTTERANCES + 1
            or not isinstance(self._session_root, Path)
        ):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)

    @property
    def remaining_utterances(self) -> int:
        return DIAGNOSTIC_MAX_UTTERANCES - self.complete_count

    @property
    def remaining_bytes(self) -> int:
        return DIAGNOSTIC_MAX_BYTES - self.complete_bytes


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    session_id: str
    captured_epoch: float
    pcm: bytes = field(repr=False)
    from_replay: bool
    phase_before: Literal["idle", "armed"]
    asr_state: Literal["available", "unavailable"]
    asr_text: str = field(repr=False)
    normalized_text: str = field(repr=False)
    action_code: str | None
    match_kind: str | None
    outcome_reason: str
    latency_ms: int

    def __post_init__(self) -> None:
        action_valid = (
            self.action_code is None
            and self.match_kind is None
            or self.action_code in _ACTION_CODES
            and self.match_kind in _MATCH_KINDS
        )
        if (
            _SESSION_ID.fullmatch(self.session_id) is None
            or not _finite_number(self.captured_epoch)
            or type(self.pcm) is not bytes
            or not self.pcm
            or len(self.pcm) % 2 != 0
            or len(self.pcm) > _MAX_PCM_BYTES
            or type(self.from_replay) is not bool
            or self.phase_before not in {"idle", "armed"}
            or self.asr_state not in {"available", "unavailable"}
            or type(self.asr_text) is not str
            or type(self.normalized_text) is not str
            or self.asr_state == "unavailable"
            and (self.asr_text or self.normalized_text)
            or not action_valid
            or self.outcome_reason not in _OUTCOME_REASONS
            or type(self.latency_ms) is not int
            or not 0 <= self.latency_ms <= 30_000
        ):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    complete_count: int
    complete_bytes: int
    incomplete_count: int
    queued_count: int = 0
    drop_count: int = 0
    failure_count: int = 0
    closed: bool = False


@dataclass(frozen=True, slots=True)
class DiagnosticAsrObservation:
    state: Literal["available", "unavailable"]
    text: str = field(repr=False)
    normalized_text: str = field(repr=False)


class DiagnosticAsrTap:
    """Observe exactly one existing ASR call without changing its result."""

    def __init__(self, underlying: object) -> None:
        if not callable(getattr(underlying, "transcribe", None)):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)
        self._underlying = underlying
        self._observation: DiagnosticAsrObservation | None = None
        self._lock = threading.Lock()

    def transcribe(self, pcm: bytes) -> object:
        try:
            result = self._underlying.transcribe(pcm)
            text = getattr(result, "text")
            if type(text) is not str:
                raise ValueError("voice_model_unavailable")
            observation = DiagnosticAsrObservation(
                "available", text, unicodedata.normalize("NFKC", text).strip()
            )
        except BaseException:
            with self._lock:
                self._observation = DiagnosticAsrObservation(
                    "unavailable", "", ""
                )
            raise
        with self._lock:
            self._observation = observation
        return result

    def take_observation(self) -> DiagnosticAsrObservation | None:
        with self._lock:
            observation, self._observation = self._observation, None
        return observation


Publisher = Callable[[DiagnosticSession, DiagnosticRecord], int]


class VoiceDiagnosticWriter:
    """Publish at most two retained diagnostic records without blocking Voice."""

    def __init__(
        self,
        session: DiagnosticSession,
        *,
        publisher: Publisher | None = None,
    ) -> None:
        if type(session) is not DiagnosticSession or (
            publisher is not None and not callable(publisher)
        ):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)
        self._session = session
        self._publisher = publisher or publish_diagnostic_record
        self._queue: queue.Queue[DiagnosticRecord] = queue.Queue(
            maxsize=DIAGNOSTIC_QUEUE_CAPACITY
        )
        self._slots = threading.BoundedSemaphore(DIAGNOSTIC_QUEUE_CAPACITY)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._closed = False
        self._failed = False
        self._outstanding = 0
        self._drops = 0
        self._failures = 0
        self._thread = threading.Thread(
            target=self._run,
            name="voice-diagnostic-writer",
            daemon=True,
        )
        self._thread.start()

    @property
    def session_id(self) -> str:
        return self._session.session_id

    def offer(self, record: DiagnosticRecord) -> bool:
        if type(record) is not DiagnosticRecord:
            return False
        with self._lock:
            if (
                self._closed
                or self._failed
                or record.session_id != self._session.session_id
                or self._session.remaining_utterances <= self._outstanding
            ):
                self._drops += 1
                return False
            if not self._slots.acquire(blocking=False):
                self._drops += 1
                return False
            self._outstanding += 1
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            with self._lock:
                self._outstanding -= 1
                self._drops += 1
            self._slots.release()
            return False

    def snapshot(self) -> DiagnosticSnapshot:
        with self._lock:
            return DiagnosticSnapshot(
                complete_count=self._session.complete_count,
                complete_bytes=self._session.complete_bytes,
                incomplete_count=self._failures,
                queued_count=self._outstanding,
                drop_count=self._drops,
                failure_count=self._failures,
                closed=self._closed,
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._closing.set()
        self._thread.join(DIAGNOSTIC_SETTLEMENT_SECONDS)

    def _run(self) -> None:
        while True:
            try:
                record = self._queue.get(timeout=0.05)
            except queue.Empty:
                if self._closing.is_set():
                    return
                continue
            try:
                published_bytes = self._publisher(self._session, record)
                if type(published_bytes) is not int or published_bytes <= 0:
                    raise ValueError
                with self._lock:
                    self._session = replace(
                        self._session,
                        complete_count=self._session.complete_count + 1,
                        complete_bytes=self._session.complete_bytes + published_bytes,
                        next_sequence=self._session.next_sequence + 1,
                    )
            except Exception:
                with self._lock:
                    self._failed = True
                    self._failures += 1
            finally:
                with self._lock:
                    self._outstanding -= 1
                self._slots.release()
                self._queue.task_done()
            if self._failed:
                self._discard_queued()

    def _discard_queued(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            with self._lock:
                self._outstanding -= 1
                self._drops += 1
            self._slots.release()
            self._queue.task_done()


def load_active_session(
    project_root: Path, *, now_epoch: float
) -> DiagnosticSession | None:
    """Load only a current, coherent session under the fixed private root."""

    try:
        if not _finite_number(now_epoch):
            return None
        root = Path(project_root).resolve(strict=True)
        diagnostics = root / "runtime" / "private" / "voice-diagnostics"
        sessions = diagnostics / "sessions"
        for directory in (
            root / "runtime",
            root / "runtime" / "private",
            diagnostics,
            sessions,
        ):
            _require_private_directory(directory)
        marker = _read_private_json(diagnostics / "active.json")
        session_id, created, expires = _validate_session_payload(marker)
        if not created <= now_epoch < expires:
            return None
        session_root = sessions / session_id
        audio_root = session_root / "audio"
        events_root = session_root / "events"
        for directory in (session_root, audio_root, events_root):
            _require_private_directory(directory)
        manifest = _read_private_json(session_root / "session.json")
        if _validate_session_payload(manifest) != (session_id, created, expires):
            return None
        complete_count, complete_bytes, next_sequence = _artifact_usage(
            audio_root, events_root
        )
        if (
            complete_count >= DIAGNOSTIC_MAX_UTTERANCES
            or complete_bytes >= DIAGNOSTIC_MAX_BYTES
        ):
            return None
        return DiagnosticSession(
            session_id=session_id,
            created_epoch=created,
            expires_epoch=expires,
            complete_count=complete_count,
            complete_bytes=complete_bytes,
            next_sequence=next_sequence,
            _session_root=session_root,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def publish_diagnostic_record(
    session: DiagnosticSession, record: DiagnosticRecord
) -> int:
    """Publish one no-replace WAV/event pair and return its complete byte count."""

    try:
        if (
            type(session) is not DiagnosticSession
            or type(record) is not DiagnosticRecord
            or record.session_id != session.session_id
            or not session.created_epoch <= record.captured_epoch < session.expires_epoch
            or session.remaining_utterances <= 0
        ):
            raise ValueError
        session_root = session._session_root
        audio_root = session_root / "audio"
        events_root = session_root / "events"
        for directory in (session_root, audio_root, events_root):
            _require_private_directory(directory)
        sequence = session.next_sequence
        basename = f"{sequence:06d}"
        wav_final = audio_root / f"{basename}.wav"
        event_final = events_root / f"{basename}.json"
        if wav_final.exists() or event_final.exists():
            raise ValueError

        wav_temp = _write_wave_temp(audio_root, basename, record.pcm)
        try:
            wav_size = wav_temp.stat().st_size
            event = _event_payload(record, sequence)
            event_bytes = json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            event_temp = _write_bytes_temp(events_root, basename, event_bytes)
            try:
                total = wav_size + len(event_bytes)
                if total > session.remaining_bytes:
                    raise ValueError
                _publish_no_replace(wav_temp, wav_final)
                wav_temp = None
                _publish_no_replace(event_temp, event_final)
                event_temp = None
                return total
            finally:
                _unlink_owned(event_temp)
        finally:
            _unlink_owned(wav_temp)
    except (OSError, ValueError, TypeError, wave.Error):
        raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE) from None


def _event_payload(record: DiagnosticRecord, sequence: int) -> dict[str, object]:
    duration_ms = len(record.pcm) * 1_000 // (16_000 * 2)
    return {
        "schema_version": 1,
        "session_id": record.session_id,
        "sequence": sequence,
        "captured_epoch": record.captured_epoch,
        "duration_ms": duration_ms,
        "pcm_bytes": len(record.pcm),
        "from_replay": record.from_replay,
        "phase_before": record.phase_before,
        "asr_state": record.asr_state,
        "asr_text": _bounded_text(record.asr_text),
        "normalized_text": _bounded_text(record.normalized_text),
        "action_code": record.action_code,
        "match_kind": record.match_kind,
        "outcome_reason": record.outcome_reason,
        "latency_ms": record.latency_ms,
        "audio_file": f"audio/{sequence:06d}.wav",
    }


def _bounded_text(value: str) -> str:
    return "".join(
        character
        for character in value
        if not unicodedata.category(character).startswith("C")
    ).strip()[:DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS]


def _validate_session_payload(
    payload: object,
) -> tuple[str, float, float]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "session_id",
        "created_epoch",
        "expires_epoch",
        "max_utterances",
        "max_bytes",
    }:
        raise ValueError
    session_id = payload["session_id"]
    created = payload["created_epoch"]
    expires = payload["expires_epoch"]
    if (
        payload["schema_version"] != 1
        or type(session_id) is not str
        or _SESSION_ID.fullmatch(session_id) is None
        or not _finite_number(created)
        or not _finite_number(expires)
        or float(expires) - float(created) != DIAGNOSTIC_LIFETIME_SECONDS
        or payload["max_utterances"] != DIAGNOSTIC_MAX_UTTERANCES
        or payload["max_bytes"] != DIAGNOSTIC_MAX_BYTES
    ):
        raise ValueError
    return session_id, float(created), float(expires)


def _artifact_usage(audio_root: Path, events_root: Path) -> tuple[int, int, int]:
    audio = _private_artifacts(audio_root, ".wav")
    events = _private_artifacts(events_root, ".json")
    complete = set(audio) & set(events)
    complete_bytes = sum(audio[number] + events[number] for number in complete)
    all_sequences = set(audio) | set(events)
    next_sequence = max(all_sequences, default=0) + 1
    if (
        len(complete) > DIAGNOSTIC_MAX_UTTERANCES
        or complete_bytes > DIAGNOSTIC_MAX_BYTES
        or next_sequence > DIAGNOSTIC_MAX_UTTERANCES + 1
    ):
        raise ValueError
    return len(complete), complete_bytes, next_sequence


def _private_artifacts(root: Path, suffix: str) -> dict[int, int]:
    result: dict[int, int] = {}
    for child in root.iterdir():
        match = _ARTIFACT_NAME.fullmatch(child.name)
        if match is None or child.suffix != suffix:
            raise ValueError
        info = child.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError
        result[int(match.group("sequence"))] = info.st_size
    return result


def _require_private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError


def _read_private_json(path: Path) -> object:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size <= 0
            or info.st_size > _MAX_METADATA_BYTES
        ):
            raise ValueError
        data = os.read(descriptor, _MAX_METADATA_BYTES + 1)
        if len(data) != info.st_size:
            raise ValueError
        return json.loads(data.decode("utf-8"))
    finally:
        os.close(descriptor)


def _write_wave_temp(root: Path, basename: str, pcm: bytes) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{basename}.", suffix=".tmp", dir=root)
    os.close(descriptor)
    path = Path(name)
    os.chmod(path, 0o600)
    try:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(pcm)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return path
    except Exception:
        _unlink_owned(path)
        raise


def _write_bytes_temp(root: Path, basename: str, data: bytes) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{basename}.", suffix=".tmp", dir=root)
    path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(data):
            written += os.write(descriptor, data[written:])
        os.fsync(descriptor)
        return path
    except Exception:
        _unlink_owned(path)
        raise
    finally:
        os.close(descriptor)


def _publish_no_replace(temporary: Path, final: Path) -> None:
    os.link(temporary, final, follow_symlinks=False)
    temporary.unlink()
    _fsync_directory(final.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _unlink_owned(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _finite_number(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


__all__ = [
    "DIAGNOSTIC_LIFETIME_SECONDS",
    "DIAGNOSTIC_MAX_BYTES",
    "DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS",
    "DIAGNOSTIC_MAX_UTTERANCES",
    "DIAGNOSTIC_QUEUE_CAPACITY",
    "DIAGNOSTIC_SETTLEMENT_SECONDS",
    "DiagnosticRecord",
    "DiagnosticAsrObservation",
    "DiagnosticAsrTap",
    "DiagnosticSession",
    "DiagnosticSnapshot",
    "VoiceDiagnosticWriter",
    "load_active_session",
    "publish_diagnostic_record",
]
