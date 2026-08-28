from __future__ import annotations

import json
import os
import stat
import threading
import wave
from dataclasses import dataclass
from pathlib import Path

import pytest

from services.voice import diagnostic as diagnostic_module
from services.voice.diagnostic import (
    DIAGNOSTIC_LIFETIME_SECONDS,
    DIAGNOSTIC_MAX_BYTES,
    DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS,
    DIAGNOSTIC_MAX_UTTERANCES,
    DIAGNOSTIC_QUEUE_CAPACITY,
    DIAGNOSTIC_SETTLEMENT_SECONDS,
    DiagnosticAsrTap,
    DiagnosticRecord,
    VoiceDiagnosticWriter,
    load_active_session,
    load_latest_retained_session,
    load_marker_session,
    publish_diagnostic_record,
    read_retained_diagnostic_sample,
    snapshot_session_artifacts,
)


SESSION_ID = "a" * 32
CREATED_EPOCH = 1_000.0
EXPIRES_EPOCH = CREATED_EPOCH + 1_800.0


def _private_dir(path: Path) -> None:
    path.mkdir()
    path.chmod(0o700)


def _private_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _session_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": SESSION_ID,
        "created_epoch": CREATED_EPOCH,
        "expires_epoch": EXPIRES_EPOCH,
        "max_utterances": 50,
        "max_bytes": 16_777_216,
    }


def _valid_tree(project_root: Path) -> Path:
    runtime = project_root / "runtime"
    private = runtime / "private"
    diagnostics = private / "voice-diagnostics"
    sessions = diagnostics / "sessions"
    session = sessions / SESSION_ID
    audio = session / "audio"
    events = session / "events"
    runtime.mkdir()
    runtime.chmod(0o755)
    for path in (private, diagnostics, sessions, session, audio, events):
        _private_dir(path)
    lock = diagnostics / ".lifecycle.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    _private_json(diagnostics / "active.json", _session_payload())
    _private_json(session / "session.json", _session_payload())
    return session


def _record(*, transcript: str = "开始喂奶") -> DiagnosticRecord:
    return DiagnosticRecord(
        session_id=SESSION_ID,
        captured_epoch=1_100.0,
        pcm=b"\x01\x00" * 1_600,
        from_replay=False,
        phase_before="armed",
        asr_state="available",
        asr_text=transcript,
        normalized_text=transcript,
        action_code="feeding_command",
        match_kind="exact",
        outcome_reason="listen_only_acknowledged",
        latency_ms=123,
    )


def test_fixed_limits_bound_the_real_session_behavior(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)

    assert session is not None
    assert session.expires_epoch - session.created_epoch == 1_800.0
    assert session.remaining_utterances == 50
    assert session.remaining_bytes == 16_777_216
    assert (
        DIAGNOSTIC_LIFETIME_SECONDS,
        DIAGNOSTIC_MAX_UTTERANCES,
        DIAGNOSTIC_MAX_BYTES,
        DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS,
        DIAGNOSTIC_QUEUE_CAPACITY,
        DIAGNOSTIC_SETTLEMENT_SECONDS,
    ) == (1_800, 50, 16_777_216, 256, 2, 5.0)
    assert str(tmp_path) not in repr(session)


def test_absent_marker_keeps_default_path_memory_only(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)

    assert load_active_session(tmp_path, now_epoch=1_200.0) is None
    assert list(runtime.iterdir()) == []


@pytest.mark.parametrize("now_epoch", [999.0, 2_800.0, 2_900.0])
def test_marker_outside_its_current_window_is_disabled(
    tmp_path: Path, now_epoch: float
) -> None:
    _valid_tree(tmp_path)

    assert load_active_session(tmp_path, now_epoch=now_epoch) is None


def test_symlinked_private_parent_is_rejected_before_session_read(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    _private_dir(outside)
    runtime = tmp_path / "runtime"
    _private_dir(runtime)
    (runtime / "private").symlink_to(outside, target_is_directory=True)

    assert load_active_session(tmp_path, now_epoch=1_200.0) is None


@pytest.mark.parametrize("mode", [0o755, 0o770])
def test_permissive_private_directory_is_rejected(
    tmp_path: Path, mode: int
) -> None:
    session_root = _valid_tree(tmp_path)
    session_root.chmod(mode)

    assert load_active_session(tmp_path, now_epoch=1_200.0) is None


def test_record_publication_creates_one_private_correlated_pair(
    tmp_path: Path,
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None

    published_bytes = publish_diagnostic_record(session, _record())

    wav_path = session_root / "audio" / "000001.wav"
    event_path = session_root / "events" / "000001.json"
    assert published_bytes == wav_path.stat().st_size + event_path.stat().st_size
    assert wav_path.stat().st_mode & 0o777 == 0o600
    assert event_path.stat().st_mode & 0o777 == 0o600
    with wave.open(str(wav_path), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == b"\x01\x00" * 1_600
    event = json.loads(event_path.read_text(encoding="utf-8"))
    assert event == {
        "action_code": "feeding_command",
        "asr_state": "available",
        "asr_text": "开始喂奶",
        "audio_file": "audio/000001.wav",
        "captured_epoch": 1_100.0,
        "duration_ms": 100,
        "from_replay": False,
        "latency_ms": 123,
        "match_kind": "exact",
        "normalized_text": "开始喂奶",
        "outcome_reason": "listen_only_acknowledged",
        "pcm_bytes": 3_200,
        "phase_before": "armed",
        "schema_version": 1,
        "sequence": 1,
        "session_id": SESSION_ID,
    }


def test_latest_retained_session_is_read_only_and_discards_private_text(
    tmp_path: Path,
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    wake = DiagnosticRecord(
        session_id=SESSION_ID,
        captured_epoch=1_100.0,
        pcm=b"\x01\x00" * 1_600,
        from_replay=False,
        phase_before="idle",
        asr_state="available",
        asr_text="synthetic wake",
        normalized_text="synthetic wake",
        action_code=None,
        match_kind=None,
        outcome_reason="listen_only_armed",
        latency_ms=10,
    )
    publish_diagnostic_record(session, wake)
    session = load_marker_session(tmp_path)
    assert session is not None
    followup = DiagnosticRecord(
        session_id=SESSION_ID,
        captured_epoch=1_101.0,
        pcm=b"\x02\x00" * 1_600,
        from_replay=False,
        phase_before="armed",
        asr_state="available",
        asr_text="private mismatch",
        normalized_text="private mismatch",
        action_code=None,
        match_kind=None,
        outcome_reason="listen_only_followup_far",
        latency_ms=12,
    )
    publish_diagnostic_record(session, followup)
    (session_root.parents[1] / "active.json").unlink()

    retained = load_latest_retained_session(tmp_path)
    assert retained is not None
    assert retained.complete_count == 2
    sample = read_retained_diagnostic_sample(retained, 2)

    assert sample.sequence == 2
    assert sample.pcm == b"\x02\x00" * 1_600
    assert sample.phase_before == "armed"
    assert sample.outcome_reason == "listen_only_followup_far"
    assert "private" not in repr(sample)
    assert not hasattr(sample, "asr_text")
    assert sorted(path.name for path in (session_root / "audio").iterdir()) == [
        "000001.wav",
        "000002.wav",
    ]


def test_publication_sanitizes_bounded_text_without_overwriting(
    tmp_path: Path,
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    long_text = "\x00" + "开" * 300 + "\n"

    publish_diagnostic_record(session, _record(transcript=long_text))
    event_path = session_root / "events" / "000001.json"
    event = json.loads(event_path.read_text(encoding="utf-8"))
    assert event["asr_text"] == "开" * 256
    assert event["normalized_text"] == "开" * 256

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    assert json.loads(event_path.read_text(encoding="utf-8")) == event


def test_hard_linked_marker_is_rejected(tmp_path: Path) -> None:
    session_root = _valid_tree(tmp_path)
    marker = session_root.parents[1] / "active.json"
    os.link(marker, tmp_path / "marker-link.json")

    assert load_active_session(tmp_path, now_epoch=1_200.0) is None


@dataclass(frozen=True)
class _AsrResult:
    text: str


class _Asr:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def transcribe(self, _pcm: bytes) -> object:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_asr_tap_observes_one_real_call_and_consumes_it_once() -> None:
    underlying = _Asr(_AsrResult("  开始喂奶  "))
    tap = DiagnosticAsrTap(underlying)

    result = tap.transcribe(b"\x01\x00")

    assert result is underlying.result
    assert underlying.calls == 1
    observation = tap.take_observation()
    assert observation is not None
    assert (observation.state, observation.text, observation.normalized_text) == (
        "available",
        "  开始喂奶  ",
        "开始喂奶",
    )
    assert "开始喂奶" not in repr(observation)
    assert tap.take_observation() is None


def test_asr_tap_replaces_stale_text_with_unavailable_on_failure() -> None:
    underlying = _Asr(_AsrResult("小小"))
    tap = DiagnosticAsrTap(underlying)
    tap.transcribe(b"\x01\x00")
    underlying.result = ValueError("private-error")

    with pytest.raises(ValueError, match="private-error"):
        tap.transcribe(b"\x01\x00")

    observation = tap.take_observation()
    assert observation is not None
    assert (observation.state, observation.text, observation.normalized_text) == (
        "unavailable",
        "",
        "",
    )
    assert tap.take_observation() is None


def test_asr_tap_and_queued_record_bound_text_before_retention() -> None:
    long_text = "开" * 1_000_000
    tap = DiagnosticAsrTap(_Asr(_AsrResult(long_text)))

    tap.transcribe(b"\x01\x00")
    observation = tap.take_observation()
    record = _record(transcript=long_text)

    assert observation is not None
    assert len(observation.text) == DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS
    assert len(observation.normalized_text) == DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS
    assert len(record.asr_text) == DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS
    assert len(record.normalized_text) == DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS


def test_writer_bounds_retained_records_while_publisher_is_blocked(
    tmp_path: Path,
) -> None:
    _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    entered = threading.Event()
    release = threading.Event()

    def blocked(_session, _record) -> int:
        entered.set()
        assert release.wait(2.0)
        return 100

    writer = VoiceDiagnosticWriter(session, publisher=blocked)
    first = _record()
    second = _record()
    third = _record()
    assert writer.offer(first) is True
    assert entered.wait(1.0)
    assert writer.offer(second) is True
    assert writer.offer(third) is False
    assert writer.snapshot().drop_count == 1

    release.set()
    writer.close()
    snapshot = writer.snapshot()
    assert snapshot.complete_count == 2
    assert snapshot.complete_bytes == 200
    assert snapshot.queued_count == 0
    assert snapshot.closed is True


def test_writer_closes_admission_after_publication_failure(tmp_path: Path) -> None:
    _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None

    def failed(_session, _record) -> int:
        raise ValueError("private-error")

    writer = VoiceDiagnosticWriter(session, publisher=failed)
    assert writer.offer(_record()) is True
    writer.close()
    snapshot = writer.snapshot()
    assert snapshot.failure_count == 1
    assert snapshot.complete_count == 0
    assert writer.offer(_record()) is False


def test_writer_advances_sequence_for_real_publication(tmp_path: Path) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    writer = VoiceDiagnosticWriter(session)

    assert writer.offer(_record()) is True
    assert writer.offer(_record()) is True
    writer.close()

    assert sorted(path.name for path in (session_root / "audio").iterdir()) == [
        "000001.wav",
        "000002.wav",
    ]
    assert sorted(path.name for path in (session_root / "events").iterdir()) == [
        "000001.json",
        "000002.json",
    ]


def test_writer_discards_queued_work_when_bounded_close_returns(
    tmp_path: Path, monkeypatch
) -> None:
    _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked(_session, _record) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            second_entered.set()
        entered.set()
        release.wait(1.0)
        return 100

    monkeypatch.setattr(diagnostic_module, "DIAGNOSTIC_SETTLEMENT_SECONDS", 0.01)
    writer = VoiceDiagnosticWriter(session, publisher=blocked)
    assert writer.offer(_record()) is True
    assert entered.wait(1.0)
    assert writer.offer(_record()) is True

    writer.close()
    assert writer.snapshot().queued_count == 1
    release.set()

    assert not second_entered.wait(0.2)
    assert calls == 1
    assert writer.snapshot().queued_count == 0
    assert writer.snapshot().complete_count == 0


def test_orphan_consumes_one_of_the_fifty_sequence_slots(tmp_path: Path) -> None:
    session_root = _valid_tree(tmp_path)
    for sequence in range(1, 50):
        for directory, suffix in (("audio", "wav"), ("events", "json")):
            artifact = session_root / directory / f"{sequence:06d}.{suffix}"
            artifact.write_bytes(b"x")
            artifact.chmod(0o600)
    orphan = session_root / "audio/000050.wav"
    orphan.write_bytes(b"x")
    orphan.chmod(0o600)

    retained = load_marker_session(tmp_path)
    assert retained is not None
    assert retained.complete_count == 49
    assert retained.remaining_utterances == 0
    assert load_active_session(tmp_path, now_epoch=1_200.0) is None


def test_sequence_zero_artifact_is_rejected_instead_of_bypassing_capacity(
    tmp_path: Path,
) -> None:
    session_root = _valid_tree(tmp_path)
    for directory, suffix in (("audio", "wav"), ("events", "json")):
        artifact = session_root / directory / f"000000.{suffix}"
        artifact.write_bytes(b"x")
        artifact.chmod(0o600)

    assert load_marker_session(tmp_path) is None


def test_parent_swap_before_publication_never_writes_outside_session(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    outside = tmp_path / "outside"
    _private_dir(outside)
    real_write_wave = diagnostic_module._write_wave_temp

    def swapped_parent(
        root: Path, basename: str, pcm: bytes, *, directory_fd: int
    ) -> str:
        root.rename(root.with_name("audio-original"))
        root.symlink_to(outside, target_is_directory=True)
        return real_write_wave(
            root, basename, pcm, directory_fd=directory_fd
        )

    monkeypatch.setattr(diagnostic_module, "_write_wave_temp", swapped_parent)
    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    assert list(outside.iterdir()) == []


def test_cancelled_publication_retains_only_private_uncommitted_temps(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    cancelled = threading.Event()
    real_write_event = diagnostic_module._write_bytes_temp_at

    def cancel_after_event_write(
        directory_fd: int, basename: str, data: bytes
    ):
        temporary = real_write_event(directory_fd, basename, data)
        cancelled.set()
        return temporary

    monkeypatch.setattr(
        diagnostic_module, "_write_bytes_temp_at", cancel_after_event_write
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(
            session, _record(), cancelled=cancelled.is_set
        )
    for directory in (session_root / "audio", session_root / "events"):
        entries = list(directory.iterdir())
        assert len(entries) == 1
        assert entries[0].name.endswith(".tmp")
        assert stat.S_IMODE(entries[0].stat().st_mode) == 0o600
    retained = load_marker_session(tmp_path)
    assert retained is not None
    snapshot = snapshot_session_artifacts(retained)
    assert snapshot.complete_count == 0
    assert snapshot.incomplete_count == 1
    assert retained.next_sequence == 2


@pytest.mark.parametrize(
    ("name", "mode"),
    (
        (".000001.not-hex.tmp", 0o600),
        (".000001.0123456789abcdef.tmp", 0o644),
        (".000001.json.0123456789abcdef.quarantine", 0o600),
    ),
)
def test_untrusted_uncommitted_artifact_shape_fails_closed(
    tmp_path: Path, name: str, mode: int
) -> None:
    session_root = _valid_tree(tmp_path)
    artifact = session_root / "audio" / name
    artifact.write_bytes(b"synthetic")
    artifact.chmod(mode)

    assert load_marker_session(tmp_path) is None


def test_duplicate_pending_sequence_fails_closed(tmp_path: Path) -> None:
    session_root = _valid_tree(tmp_path)
    for token in ("0123456789abcdef", "fedcba9876543210"):
        artifact = session_root / "audio" / f".000001.{token}.tmp"
        artifact.write_bytes(b"synthetic")
        artifact.chmod(0o600)

    assert load_marker_session(tmp_path) is None


def test_cancellation_during_final_authority_check_never_completes_pair(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    cancelled = threading.Event()
    real_require_authority = diagnostic_module._require_session_authority
    calls = 0

    def cancel_during_final_check(*args) -> None:
        nonlocal calls
        calls += 1
        real_require_authority(*args)
        if calls == 3:
            cancelled.set()

    monkeypatch.setattr(
        diagnostic_module,
        "_require_session_authority",
        cancel_during_final_check,
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(
            session, _record(), cancelled=cancelled.is_set
        )
    assert (session_root / "audio/000001.wav").is_file()
    assert not (session_root / "events/000001.json").exists()


def test_cancellation_at_event_rename_rolls_back_complete_pair(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    cancelled = threading.Event()
    real_rename = diagnostic_module._rename_no_replace_at

    def cancel_at_event_rename(
        directory_fd: int, source: str, destination: str
    ) -> None:
        if destination.endswith(".json"):
            cancelled.set()
        real_rename(directory_fd, source, destination)

    monkeypatch.setattr(
        diagnostic_module, "_rename_no_replace_at", cancel_at_event_rename
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(
            session, _record(), cancelled=cancelled.is_set
        )
    assert (session_root / "audio/000001.wav").is_file()
    assert not (session_root / "events/000001.json").exists()


def test_replaced_temporary_name_is_not_published(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    real_require_bindings = diagnostic_module._require_tree_bindings

    def replace_event_temp(*args) -> None:
        real_require_bindings(*args)
        events_fd = args[3]
        temporaries = [
            name for name in os.listdir(events_fd) if name.endswith(".tmp")
        ]
        if not temporaries:
            return
        temporary = temporaries[0]
        os.unlink(temporary, dir_fd=events_fd)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
            dir_fd=events_fd,
        )
        try:
            assert os.write(descriptor, b"synthetic replacement") > 0
        finally:
            os.close(descriptor)

    monkeypatch.setattr(
        diagnostic_module, "_require_tree_bindings", replace_event_temp
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    assert not (session_root / "events/000001.json").exists()


def test_temporary_mode_change_after_validation_leaves_no_final(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    real_require_identity = diagnostic_module._require_temporary_identity
    changed = False

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    monkeypatch.setattr(
        diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    assert not (session_root / "audio/000001.wav").exists()


def test_rollback_quarantine_is_retained_private_and_directory_is_synced(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    real_require_identity = diagnostic_module._require_temporary_identity
    real_rename = diagnostic_module._rename_no_replace_at
    changed = False

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    def occupy_original_after_rename(
        directory_fd: int, source: str, destination: str
    ) -> None:
        real_rename(directory_fd, source, destination)
        if destination.endswith(".wav"):
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            os.close(descriptor)

    fsync_calls: list[int] = []
    real_fsync = diagnostic_module.os.fsync

    def record_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(
        diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )
    monkeypatch.setattr(
        diagnostic_module,
        "_rename_no_replace_at",
        occupy_original_after_rename,
    )
    monkeypatch.setattr(diagnostic_module.os, "fsync", record_fsync)

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    audio_names = [path.name for path in (session_root / "audio").iterdir()]
    quarantine = [
        path
        for path in (session_root / "audio").iterdir()
        if path.name.endswith(".quarantine")
    ]
    assert len(quarantine) == 1
    assert stat.S_IMODE(quarantine[0].stat().st_mode) == 0o600
    assert "000001.wav" not in audio_names
    assert fsync_calls


def test_replaced_rollback_candidate_is_not_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    session_root = _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    real_require_identity = diagnostic_module._require_temporary_identity
    real_rollback = diagnostic_module._rollback_final_at
    changed = False
    replacement: Path | None = None

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    def replace_after_rollback(directory_fd: int, temporary, final: str) -> str:
        nonlocal replacement
        candidate = real_rollback(directory_fd, temporary, final)
        held = f".{final}.held"
        os.rename(
            candidate,
            held,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        descriptor = os.open(
            candidate,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        os.close(descriptor)
        replacement = session_root / "audio" / candidate
        return candidate

    monkeypatch.setattr(
        diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )
    monkeypatch.setattr(
        diagnostic_module, "_rollback_final_at", replace_after_rollback
    )

    with pytest.raises(ValueError, match="^voice_diagnostic_unavailable$"):
        publish_diagnostic_record(session, _record())
    assert replacement is not None
    assert replacement.is_file()


def test_close_error_cannot_close_a_reused_descriptor(
    tmp_path: Path, monkeypatch
) -> None:
    _valid_tree(tmp_path)
    session = load_active_session(tmp_path, now_epoch=1_200.0)
    assert session is not None
    real_write_wave = diagnostic_module._write_wave_temp
    real_close = diagnostic_module.os.close
    target: list[int] = []
    reused: list[int] = []
    raised = False

    def remember_wave(*args, **kwargs):
        temporary = real_write_wave(*args, **kwargs)
        target.append(temporary.descriptor)
        return temporary

    def close_then_reuse(descriptor: int) -> None:
        nonlocal raised
        if target and descriptor == target[0] and not raised:
            raised = True
            real_close(descriptor)
            reused.append(os.open("/dev/null", os.O_RDONLY))
            raise OSError("synthetic close error")
        real_close(descriptor)

    monkeypatch.setattr(diagnostic_module, "_write_wave_temp", remember_wave)
    monkeypatch.setattr(diagnostic_module.os, "close", close_then_reuse)
    try:
        assert publish_diagnostic_record(session, _record()) > 0
        assert target and reused == target
        os.fstat(reused[0])
    finally:
        monkeypatch.undo()
        if reused:
            try:
                real_close(reused[0])
            except OSError:
                pass


def test_temporary_creation_failure_closes_fd_and_retains_private_name(
    tmp_path: Path, monkeypatch
) -> None:
    _private_dir(tmp_path / "artifacts")
    directory_fd = os.open(tmp_path / "artifacts", os.O_RDONLY)
    real_open = diagnostic_module.os.open
    opened: list[int] = []

    def recording_open(*args, **kwargs) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(diagnostic_module.os, "open", recording_open)
    monkeypatch.setattr(
        diagnostic_module.os,
        "fchmod",
        lambda _descriptor, _mode: (_ for _ in ()).throw(OSError()),
    )
    try:
        with pytest.raises(OSError):
            diagnostic_module._new_temp_file(directory_fd, "000001")
    finally:
        monkeypatch.undo()
        os.close(directory_fd)

    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    retained = list((tmp_path / "artifacts").iterdir())
    assert len(retained) == 1
    assert retained[0].name.endswith(".tmp")
    assert stat.S_IMODE(retained[0].stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("system", "function_name", "expected_flag"),
    (("Darwin", "renameatx_np", 4), ("Linux", "renameat2", 1)),
)
def test_native_no_replace_uses_platform_function_and_flag(
    monkeypatch, system: str, function_name: str, expected_flag: int
) -> None:
    calls: list[tuple[object, ...]] = []

    class Function:
        argtypes = None
        restype = None

        def __call__(self, *args) -> int:
            calls.append(args)
            return 0

    function = Function()
    library = type("Library", (), {function_name: function})()
    monkeypatch.setattr(diagnostic_module.platform, "system", lambda: system)
    monkeypatch.setattr(
        diagnostic_module.ctypes, "CDLL", lambda *_args, **_kwargs: library
    )

    diagnostic_module._rename_no_replace_at(9, "source", "final")

    assert calls == [
        (9, b"source", 9, b"final", expected_flag)
    ]


def test_loader_closes_opened_audio_descriptor_when_events_open_fails(
    tmp_path: Path, monkeypatch
) -> None:
    _valid_tree(tmp_path)
    real_open = diagnostic_module._open_directory_at
    audio_descriptors: list[int] = []

    def fail_events(parent_fd: int, name: str, **options) -> int:
        if name == "events":
            raise OSError("synthetic events open failure")
        descriptor = real_open(parent_fd, name, **options)
        if name == "audio":
            audio_descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(diagnostic_module, "_open_directory_at", fail_events)

    assert load_marker_session(tmp_path) is None
    assert len(audio_descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(audio_descriptors[0])
