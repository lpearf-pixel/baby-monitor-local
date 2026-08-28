from __future__ import annotations

import json
import os
import wave
from pathlib import Path

import pytest

from services.voice.diagnostic import (
    DIAGNOSTIC_LIFETIME_SECONDS,
    DIAGNOSTIC_MAX_BYTES,
    DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS,
    DIAGNOSTIC_MAX_UTTERANCES,
    DIAGNOSTIC_QUEUE_CAPACITY,
    DIAGNOSTIC_SETTLEMENT_SECONDS,
    DiagnosticRecord,
    load_active_session,
    publish_diagnostic_record,
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
    for path in (runtime, private, diagnostics, sessions, session, audio, events):
        _private_dir(path)
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
