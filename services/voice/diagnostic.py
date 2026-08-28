"""Private, bounded artifacts for an explicitly supervised Voice diagnostic."""

from __future__ import annotations

import ctypes
import errno
import json
import math
import os
import platform
import queue
import re
import secrets
import stat
import threading
import unicodedata
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
_TEMP_ARTIFACT_NAME = re.compile(
    r"^\.(?P<sequence>[0-9]{6})\.[0-9a-f]{16}\.tmp$"
)
_QUARANTINE_ARTIFACT_NAME = re.compile(
    r"^\.(?P<sequence>[0-9]{6})(?P<suffix>\.wav|\.json)\."
    r"[0-9a-f]{16}\.quarantine$"
)
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
    _project_root: Path = field(repr=False)

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
            or not isinstance(self._project_root, Path)
        ):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)

    @property
    def remaining_utterances(self) -> int:
        return DIAGNOSTIC_MAX_UTTERANCES - (self.next_sequence - 1)

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
        if type(self.asr_text) is str:
            object.__setattr__(self, "asr_text", _bounded_text(self.asr_text))
        if type(self.normalized_text) is str:
            object.__setattr__(
                self, "normalized_text", _bounded_text(self.normalized_text)
            )
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
class RetainedDiagnosticSample:
    pcm: bytes = field(repr=False)
    sequence: int
    phase_before: Literal["idle", "armed"]
    outcome_reason: str
    action_code: str | None
    match_kind: str | None

    def __post_init__(self) -> None:
        if (
            type(self.pcm) is not bytes
            or not self.pcm
            or len(self.pcm) % 2
            or len(self.pcm) > _MAX_PCM_BYTES
            or type(self.sequence) is not int
            or not 1 <= self.sequence <= DIAGNOSTIC_MAX_UTTERANCES
            or self.phase_before not in {"idle", "armed"}
            or self.outcome_reason not in _OUTCOME_REASONS
            or not (
                self.action_code is None
                and self.match_kind is None
                or self.action_code in _ACTION_CODES
                and self.match_kind in _MATCH_KINDS
            )
        ):
            raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class DiagnosticAsrObservation:
    state: Literal["available", "unavailable"]
    text: str = field(repr=False)
    normalized_text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _PrivateTree:
    root: int
    runtime: int
    private: int
    diagnostics: int
    sessions: int


@dataclass(frozen=True, slots=True)
class _TemporaryArtifact:
    descriptor: int
    name: str
    device: int
    inode: int


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
                "available",
                text[:DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS],
                unicodedata.normalize("NFKC", text).strip()[
                    :DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS
                ],
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
        self._queue: queue.Queue[DiagnosticRecord] = queue.Queue(
            maxsize=DIAGNOSTIC_QUEUE_CAPACITY
        )
        self._slots = threading.BoundedSemaphore(DIAGNOSTIC_QUEUE_CAPACITY)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._abandon = threading.Event()
        self._publisher = publisher or (
            lambda current_session, record: publish_diagnostic_record(
                current_session,
                record,
                cancelled=self._abandon.is_set,
            )
        )
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
        if self._thread.is_alive():
            self._abandon.set()
            self._discard_queued()

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
                    if not self._abandon.is_set():
                        self._session = replace(
                            self._session,
                            complete_count=self._session.complete_count + 1,
                            complete_bytes=(
                                self._session.complete_bytes + published_bytes
                            ),
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
            if self._abandon.is_set():
                self._discard_queued()
                return
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
        session = load_marker_session(project_root)
        if session is None or not (
            session.created_epoch <= now_epoch < session.expires_epoch
        ):
            return None
        if (
            session.remaining_utterances <= 0
            or session.complete_bytes >= DIAGNOSTIC_MAX_BYTES
        ):
            return None
        return session
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def load_marker_session(project_root: Path) -> DiagnosticSession | None:
    """Load a coherent retained marker session regardless of its clock state."""

    try:
        root = Path(project_root).resolve(strict=True)
        with _open_private_tree(root) as tree:
            marker = _read_private_json_at(tree.diagnostics, "active.json")
            session_id, created, expires = _validate_session_payload(marker)
            session_fd = _open_directory_at(
                tree.sessions, session_id, private=True
            )
            try:
                audio_fd = _open_directory_at(session_fd, "audio", private=True)
                try:
                    events_fd = _open_directory_at(
                        session_fd, "events", private=True
                    )
                    try:
                        manifest = _read_private_json_at(
                            session_fd, "session.json"
                        )
                        if _validate_session_payload(manifest) != (
                            session_id,
                            created,
                            expires,
                        ):
                            return None
                        complete_count, complete_bytes, next_sequence = (
                            _artifact_usage_at(audio_fd, events_fd)
                        )
                        return DiagnosticSession(
                            session_id=session_id,
                            created_epoch=created,
                            expires_epoch=expires,
                            complete_count=complete_count,
                            complete_bytes=complete_bytes,
                            next_sequence=next_sequence,
                            _session_root=(
                                root
                                / "runtime/private/voice-diagnostics/sessions"
                                / session_id
                            ),
                            _project_root=root,
                        )
                    finally:
                        os.close(events_fd)
                finally:
                    os.close(audio_fd)
            finally:
                os.close(session_fd)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def load_latest_retained_session(project_root: Path) -> DiagnosticSession | None:
    """Select the newest coherent retained session without requiring an active marker."""

    try:
        root = Path(project_root).resolve(strict=True)
        candidates: list[DiagnosticSession] = []
        with _open_private_tree(root) as tree:
            names = os.listdir(tree.sessions)
            if not 1 <= len(names) <= 128:
                raise ValueError
            for session_id in names:
                if _SESSION_ID.fullmatch(session_id) is None:
                    raise ValueError
                session_fd = _open_directory_at(
                    tree.sessions, session_id, private=True
                )
                try:
                    manifest = _read_private_json_at(session_fd, "session.json")
                    checked_id, created, expires = _validate_session_payload(manifest)
                    if checked_id != session_id:
                        raise ValueError
                    audio_fd = _open_directory_at(session_fd, "audio", private=True)
                    try:
                        events_fd = _open_directory_at(
                            session_fd, "events", private=True
                        )
                        try:
                            _require_tree_bindings(
                                tree,
                                session_fd,
                                audio_fd,
                                events_fd,
                                session_id,
                            )
                            complete_count, complete_bytes, next_sequence = (
                                _artifact_usage_at(audio_fd, events_fd)
                            )
                        finally:
                            os.close(events_fd)
                    finally:
                        os.close(audio_fd)
                    candidates.append(
                        DiagnosticSession(
                            session_id=session_id,
                            created_epoch=created,
                            expires_epoch=expires,
                            complete_count=complete_count,
                            complete_bytes=complete_bytes,
                            next_sequence=next_sequence,
                            _session_root=(
                                root
                                / "runtime/private/voice-diagnostics/sessions"
                                / session_id
                            ),
                            _project_root=root,
                        )
                    )
                finally:
                    os.close(session_fd)
        latest_epoch = max(item.created_epoch for item in candidates)
        latest = [item for item in candidates if item.created_epoch == latest_epoch]
        if len(latest) != 1:
            raise ValueError
        return latest[0]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def read_retained_diagnostic_sample(
    session: DiagnosticSession, sequence: int
) -> RetainedDiagnosticSample:
    """Read one complete retained pair and discard its private transcript metadata."""

    try:
        if (
            type(session) is not DiagnosticSession
            or type(sequence) is not int
            or not 1 <= sequence <= DIAGNOSTIC_MAX_UTTERANCES
        ):
            raise ValueError
        with _open_session_tree(session) as opened:
            _tree, _session_fd, audio_fd, events_fd = opened
            audio, audio_pending = _private_artifacts_at(audio_fd, ".wav")
            events, event_pending = _private_artifacts_at(events_fd, ".json")
            if (
                sequence not in audio
                or sequence not in events
                or sequence in audio_pending
                or sequence in event_pending
            ):
                raise ValueError
            basename = f"{sequence:06d}"
            pcm = _read_private_wave_at(audio_fd, f"{basename}.wav")
            payload = _read_private_json_at(events_fd, f"{basename}.json")
        expected_keys = {
            "action_code",
            "asr_state",
            "asr_text",
            "audio_file",
            "captured_epoch",
            "duration_ms",
            "from_replay",
            "latency_ms",
            "match_kind",
            "normalized_text",
            "outcome_reason",
            "pcm_bytes",
            "phase_before",
            "schema_version",
            "sequence",
            "session_id",
        }
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError
        record = DiagnosticRecord(
            session_id=payload["session_id"],
            captured_epoch=payload["captured_epoch"],
            pcm=pcm,
            from_replay=payload["from_replay"],
            phase_before=payload["phase_before"],
            asr_state=payload["asr_state"],
            asr_text=payload["asr_text"],
            normalized_text=payload["normalized_text"],
            action_code=payload["action_code"],
            match_kind=payload["match_kind"],
            outcome_reason=payload["outcome_reason"],
            latency_ms=payload["latency_ms"],
        )
        if (
            payload["schema_version"] != 1
            or payload["session_id"] != session.session_id
            or payload["sequence"] != sequence
            or payload["audio_file"] != f"audio/{sequence:06d}.wav"
            or payload["pcm_bytes"] != len(pcm)
            or payload["duration_ms"] != len(pcm) * 1_000 // (16_000 * 2)
        ):
            raise ValueError
        return RetainedDiagnosticSample(
            pcm=pcm,
            sequence=sequence,
            phase_before=record.phase_before,
            outcome_reason=record.outcome_reason,
            action_code=record.action_code,
            match_kind=record.match_kind,
        )
    except (OSError, TypeError, ValueError, wave.Error):
        raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE) from None


def _read_private_wave_at(directory_fd: int, name: str) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 44 < info.st_size <= DIAGNOSTIC_MAX_BYTES
        ):
            raise ValueError
        with os.fdopen(os.dup(descriptor), "rb") as source:
            with wave.open(source, "rb") as wav:
                if (
                    wav.getnchannels() != 1
                    or wav.getsampwidth() != 2
                    or wav.getframerate() != 16_000
                    or wav.getcomptype() != "NONE"
                    or not 1 <= wav.getnframes() <= 16_000 * 8
                ):
                    raise ValueError
                pcm = wav.readframes(wav.getnframes())
        if not pcm or len(pcm) > _MAX_PCM_BYTES:
            raise ValueError
        return pcm
    finally:
        os.close(descriptor)


def publish_diagnostic_record(
    session: DiagnosticSession,
    record: DiagnosticRecord,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    """Publish one no-replace WAV/event pair and return its complete byte count."""

    try:
        if (
            type(session) is not DiagnosticSession
            or type(record) is not DiagnosticRecord
            or record.session_id != session.session_id
            or not session.created_epoch <= record.captured_epoch < session.expires_epoch
            or session.remaining_utterances <= 0
            or cancelled is not None
            and cancelled()
        ):
            raise ValueError
        is_cancelled = cancelled or (lambda: False)
        with _open_session_tree(session) as opened:
            tree, session_fd, audio_fd, events_fd = opened
            _require_session_authority(tree.diagnostics, session_fd, session)
            sequence = session.next_sequence
            basename = f"{sequence:06d}"
            wav_final = f"{basename}.wav"
            event_final = f"{basename}.json"
            if _entry_exists(audio_fd, wav_final) or _entry_exists(
                events_fd, event_final
            ):
                raise ValueError

            wav_temp = _write_wave_temp(
                session._session_root / "audio",
                basename,
                record.pcm,
                directory_fd=audio_fd,
            )
            try:
                if is_cancelled():
                    raise ValueError
                wav_size = os.fstat(wav_temp.descriptor).st_size
                event = _event_payload(record, sequence)
                event_bytes = json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                event_temp = _write_bytes_temp_at(
                    events_fd, basename, event_bytes
                )
                try:
                    if is_cancelled():
                        raise ValueError
                    total = wav_size + len(event_bytes)
                    if total > session.remaining_bytes:
                        raise ValueError
                    _require_tree_bindings(
                        tree,
                        session_fd,
                        audio_fd,
                        events_fd,
                        session.session_id,
                    )
                    _require_session_authority(
                        tree.diagnostics, session_fd, session
                    )
                    if is_cancelled():
                        raise ValueError
                    _publish_no_replace_at(
                        audio_fd,
                        wav_temp,
                        wav_final,
                        cancelled=is_cancelled,
                    )
                    published_wav = wav_temp
                    wav_temp = None
                    _close_descriptor_once(published_wav.descriptor)
                    if is_cancelled():
                        raise ValueError
                    _require_session_authority(
                        tree.diagnostics, session_fd, session
                    )
                    if is_cancelled():
                        raise ValueError
                    _publish_no_replace_at(
                        events_fd,
                        event_temp,
                        event_final,
                        cancelled=is_cancelled,
                    )
                    published_event = event_temp
                    event_temp = None
                    _close_descriptor_once(published_event.descriptor)
                    return total
                finally:
                    _unlink_owned_at(events_fd, event_temp)
            finally:
                _unlink_owned_at(audio_fd, wav_temp)
    except (OSError, ValueError, TypeError, wave.Error):
        raise ValueError(VOICE_DIAGNOSTIC_UNAVAILABLE) from None


def snapshot_session_artifacts(session: DiagnosticSession) -> DiagnosticSnapshot:
    """Return bounded artifact counts without opening audio or event payloads."""

    try:
        if type(session) is not DiagnosticSession:
            raise ValueError
        with _open_session_tree(session) as opened:
            _tree, _session_fd, audio_fd, events_fd = opened
            audio, audio_pending = _private_artifacts_at(audio_fd, ".wav")
            events, event_pending = _private_artifacts_at(events_fd, ".json")
        complete = set(audio) & set(events)
        incomplete = (
            set(audio) ^ set(events)
        ) | audio_pending | event_pending
        complete_bytes = sum(audio[number] + events[number] for number in complete)
        if (
            len(complete) > DIAGNOSTIC_MAX_UTTERANCES
            or len(incomplete) > DIAGNOSTIC_MAX_UTTERANCES
            or complete_bytes > DIAGNOSTIC_MAX_BYTES
        ):
            raise ValueError
        return DiagnosticSnapshot(
            complete_count=len(complete),
            complete_bytes=complete_bytes,
            incomplete_count=len(incomplete),
        )
    except (OSError, ValueError, TypeError):
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


def _artifact_usage_at(audio_fd: int, events_fd: int) -> tuple[int, int, int]:
    audio, audio_pending = _private_artifacts_at(audio_fd, ".wav")
    events, event_pending = _private_artifacts_at(events_fd, ".json")
    complete = set(audio) & set(events)
    complete_bytes = sum(audio[number] + events[number] for number in complete)
    all_sequences = set(audio) | set(events) | audio_pending | event_pending
    next_sequence = max(all_sequences, default=0) + 1
    if (
        len(complete) > DIAGNOSTIC_MAX_UTTERANCES
        or complete_bytes > DIAGNOSTIC_MAX_BYTES
        or next_sequence > DIAGNOSTIC_MAX_UTTERANCES + 1
    ):
        raise ValueError
    return len(complete), complete_bytes, next_sequence


def _private_artifacts_at(
    directory_fd: int, suffix: str
) -> tuple[dict[int, int], set[int]]:
    result: dict[int, int] = {}
    pending: set[int] = set()
    names = os.listdir(directory_fd)
    if len(names) > DIAGNOSTIC_MAX_UTTERANCES:
        raise ValueError
    for name in names:
        match = _ARTIFACT_NAME.fullmatch(name)
        committed = match is not None and name.endswith(suffix)
        if not committed:
            match = _TEMP_ARTIFACT_NAME.fullmatch(name)
        if match is None:
            match = _QUARANTINE_ARTIFACT_NAME.fullmatch(name)
            if match is not None and match.group("suffix") != suffix:
                raise ValueError
        if match is None:
            raise ValueError
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_size > DIAGNOSTIC_MAX_BYTES
        ):
            raise ValueError
        sequence = int(match.group("sequence"))
        if not 1 <= sequence <= DIAGNOSTIC_MAX_UTTERANCES:
            raise ValueError
        if committed:
            result[sequence] = info.st_size
        else:
            if sequence in pending:
                raise ValueError
            pending.add(sequence)
    if set(result) & pending:
        raise ValueError
    return result, pending


def _read_private_json_at(directory_fd: int, name: str) -> object:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
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


@contextmanager
def _open_private_tree(root: Path) -> Iterator[_PrivateTree]:
    opened: list[int] = []
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
            os, "O_NOFOLLOW", 0
        )
        root_fd = os.open(root, flags)
        opened.append(root_fd)
        runtime_fd = _open_directory_at(root_fd, "runtime", owned=True)
        opened.append(runtime_fd)
        private_fd = _open_directory_at(runtime_fd, "private", private=True)
        opened.append(private_fd)
        diagnostics_fd = _open_directory_at(
            private_fd, "voice-diagnostics", private=True
        )
        opened.append(diagnostics_fd)
        sessions_fd = _open_directory_at(
            diagnostics_fd, "sessions", private=True
        )
        opened.append(sessions_fd)
        yield _PrivateTree(
            root_fd, runtime_fd, private_fd, diagnostics_fd, sessions_fd
        )
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


@contextmanager
def _open_session_tree(
    session: DiagnosticSession,
) -> Iterator[tuple[_PrivateTree, int, int, int]]:
    with _open_private_tree(session._project_root) as tree:
        session_fd = _open_directory_at(
            tree.sessions, session.session_id, private=True
        )
        try:
            audio_fd = _open_directory_at(session_fd, "audio", private=True)
            try:
                events_fd = _open_directory_at(
                    session_fd, "events", private=True
                )
                try:
                    _require_tree_bindings(
                        tree, session_fd, audio_fd, events_fd, session.session_id
                    )
                    yield tree, session_fd, audio_fd, events_fd
                finally:
                    os.close(events_fd)
            finally:
                os.close(audio_fd)
        finally:
            os.close(session_fd)


def _open_directory_at(
    parent_fd: int, name: str, *, private: bool = False, owned: bool = False
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or private
            and stat.S_IMODE(info.st_mode) != 0o700
            or owned
            and stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _require_tree_bindings(
    tree: _PrivateTree,
    session_fd: int,
    audio_fd: int,
    events_fd: int,
    session_id: str,
) -> None:
    for parent, name, child, private in (
        (tree.root, "runtime", tree.runtime, False),
        (tree.runtime, "private", tree.private, True),
        (tree.private, "voice-diagnostics", tree.diagnostics, True),
        (tree.diagnostics, "sessions", tree.sessions, True),
        (tree.sessions, session_id, session_fd, True),
        (session_fd, "audio", audio_fd, True),
        (session_fd, "events", events_fd, True),
    ):
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(child)
        for info in (entry, opened):
            mode = stat.S_IMODE(info.st_mode)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or private
                and mode != 0o700
                or not private
                and mode & 0o022
            ):
                raise ValueError
        if (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError


def _require_session_authority(
    diagnostics_fd: int, session_fd: int, session: DiagnosticSession
) -> None:
    marker = _validate_session_payload(
        _read_private_json_at(diagnostics_fd, "active.json")
    )
    manifest = _validate_session_payload(
        _read_private_json_at(session_fd, "session.json")
    )
    expected = (session.session_id, session.created_epoch, session.expires_epoch)
    if marker != expected or manifest != expected:
        raise ValueError


def _new_temp_file(directory_fd: int, basename: str) -> tuple[int, str]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for _attempt in range(8):
        name = f".{basename}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            continue
        try:
            os.fchmod(descriptor, 0o600)
            os.fstat(descriptor)
            return descriptor, name
        except Exception:
            _close_descriptor_once(descriptor)
            raise
    raise ValueError


def _write_wave_temp(
    root: Path,
    basename: str,
    pcm: bytes,
    *,
    directory_fd: int,
) -> _TemporaryArtifact:
    del root
    descriptor, name = _new_temp_file(directory_fd, basename)
    try:
        with os.fdopen(os.dup(descriptor), "w+b") as target:
            with wave.open(target, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(16_000)
                output.writeframes(pcm)
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        return _TemporaryArtifact(
            descriptor=descriptor,
            name=name,
            device=info.st_dev,
            inode=info.st_ino,
        )
    except Exception:
        _close_descriptor_once(descriptor)
        raise


def _write_bytes_temp_at(
    directory_fd: int, basename: str, data: bytes
) -> _TemporaryArtifact:
    descriptor, name = _new_temp_file(directory_fd, basename)
    try:
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count <= 0:
                raise OSError
            written += count
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        return _TemporaryArtifact(
            descriptor=descriptor,
            name=name,
            device=info.st_dev,
            inode=info.st_ino,
        )
    except Exception:
        _close_descriptor_once(descriptor)
        raise


def _publish_no_replace_at(
    directory_fd: int,
    temporary: _TemporaryArtifact,
    final: str,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    is_cancelled = cancelled or (lambda: False)
    _require_temporary_identity(directory_fd, temporary)
    if is_cancelled():
        raise ValueError
    _rename_no_replace_at(directory_fd, temporary.name, final)
    try:
        if is_cancelled():
            raise ValueError
        final_info = os.stat(
            final, dir_fd=directory_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(final_info.st_mode)
            or final_info.st_uid != os.getuid()
            or stat.S_IMODE(final_info.st_mode) != 0o600
            or final_info.st_nlink != 1
            or (final_info.st_dev, final_info.st_ino)
            != (temporary.device, temporary.inode)
        ):
            raise ValueError
        if is_cancelled():
            raise ValueError
        os.fsync(directory_fd)
        if is_cancelled():
            raise ValueError
    except Exception:
        os.fchmod(temporary.descriptor, 0o600)
        os.fsync(temporary.descriptor)
        _rollback_final_at(directory_fd, temporary, final)
        os.fsync(directory_fd)
        raise


def _rename_no_replace_at(
    directory_fd: int, source: str, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    system = platform.system()
    if system == "Darwin":
        function = library.renameatx_np
        flag = 4
    elif system == "Linux":
        function = library.renameat2
        flag = 1
    else:
        raise OSError
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        directory_fd,
        os.fsencode(source),
        directory_fd,
        os.fsencode(destination),
        flag,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(error, VOICE_DIAGNOSTIC_UNAVAILABLE)
        raise OSError(error, VOICE_DIAGNOSTIC_UNAVAILABLE)


def _rollback_final_at(
    directory_fd: int,
    temporary: _TemporaryArtifact,
    final: str,
) -> str:
    candidates = [temporary.name]
    candidates.extend(
        f".{final}.{secrets.token_hex(8)}.quarantine" for _ in range(8)
    )
    for candidate in candidates:
        try:
            _rename_no_replace_at(directory_fd, final, candidate)
            return candidate
        except FileExistsError:
            continue
    raise ValueError


def _require_temporary_identity(
    directory_fd: int, temporary: _TemporaryArtifact
) -> None:
    descriptor_info = os.fstat(temporary.descriptor)
    entry_info = os.stat(
        temporary.name, dir_fd=directory_fd, follow_symlinks=False
    )
    expected = (temporary.device, temporary.inode)
    for info in (descriptor_info, entry_info):
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != expected
        ):
            raise ValueError


def _unlink_owned_at(
    directory_fd: int, temporary: _TemporaryArtifact | None
) -> None:
    del directory_fd
    if temporary is None:
        return
    _close_descriptor_once(temporary.descriptor)


def _close_descriptor_once(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _entry_exists(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


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
    "RetainedDiagnosticSample",
    "VoiceDiagnosticWriter",
    "load_active_session",
    "load_marker_session",
    "load_latest_retained_session",
    "publish_diagnostic_record",
    "read_retained_diagnostic_sample",
    "snapshot_session_artifacts",
]
