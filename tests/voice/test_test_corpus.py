from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from services.voice.test_corpus import VoiceTestCorpusStore


def _key() -> bytes:
    return Fernet.generate_key()


def test_recording_is_disabled_until_explicit_consent(tmp_path: Path) -> None:
    store = VoiceTestCorpusStore(tmp_path / "voice-corpus", key_provider=_key)

    with pytest.raises(ValueError, match="voice_test_consent_required"):
        store.record(
            test_id="test-1",
            session_id="session-1",
            created_at=datetime.now(UTC),
            audio=b"synthetic pcm",
            recognized_text="测试",
            expected_text="测试",
            actual_reply="语音回复正常",
            expected_reply="语音回复正常",
            latency_ms=123,
            playback_status="COMPLETE",
            error_code=None,
        )
    assert not list((tmp_path / "voice-corpus").glob("**/*.*"))


def test_authorized_record_is_encrypted_private_and_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "voice-corpus"
    key = _key()
    store = VoiceTestCorpusStore(root, key_provider=lambda: key)
    store.enable("consent-synthetic-1")

    record = store.record(
        test_id="test-1",
        session_id="session-1",
        created_at=datetime(2026, 10, 22, tzinfo=UTC),
        audio=b"synthetic pcm",
        recognized_text="测试语音回复",
        expected_text="测试语音回复",
        actual_reply="语音回复正常",
        expected_reply="语音回复正常",
        latency_ms=123,
        playback_status="COMPLETE",
        error_code=None,
    )

    assert record["test_id"] == "test-1"
    assert record["audio_sha256"] == (
        "148eec3c90832fff748c402fd17de710e0dc50655c0dc6e8a651521d5cf25db6"
    )
    metadata = root / "records" / "test-1.json"
    encrypted = root / "audio" / "test-1.bin.enc"
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert root.stat().st_mode & 0o777 == 0o700
    assert b"synthetic pcm" not in encrypted.read_bytes()
    assert b"synthetic pcm" not in metadata.read_bytes()
    assert store.read_audio("test-1") == b"synthetic pcm"
    assert store.list_records()[0]["consent_reference"] == "consent-synthetic-1"


def test_revoked_consent_blocks_new_records_and_delete_removes_media(tmp_path: Path) -> None:
    store = VoiceTestCorpusStore(tmp_path / "voice-corpus", key_provider=_key)
    store.enable("consent-synthetic-1")
    store.record(
        test_id="test-1",
        session_id="session-1",
        created_at=datetime.now(UTC),
        audio=b"pcm",
        recognized_text="x",
        expected_text="x",
        actual_reply="y",
        expected_reply="y",
        latency_ms=1,
        playback_status="COMPLETE",
        error_code=None,
    )

    store.disable()
    with pytest.raises(ValueError, match="voice_test_consent_required"):
        store.record(
            test_id="test-2",
            session_id="session-2",
            created_at=datetime.now(UTC),
            audio=b"pcm",
            recognized_text="x",
            expected_text="x",
            actual_reply="y",
            expected_reply="y",
            latency_ms=1,
            playback_status="COMPLETE",
            error_code=None,
        )
    assert store.delete("test-1") is True
    assert store.list_records() == []
    assert not (tmp_path / "voice-corpus" / "audio" / "test-1.bin.enc").exists()


def test_expiry_removes_only_records_older_than_seven_days(tmp_path: Path) -> None:
    store = VoiceTestCorpusStore(tmp_path / "voice-corpus", key_provider=_key)
    store.enable("consent-synthetic-1")
    old = datetime.now(UTC) - timedelta(days=8)
    current = datetime.now(UTC) - timedelta(days=1)
    for test_id, created_at in (("old", old), ("current", current)):
        store.record(
            test_id=test_id,
            session_id=test_id,
            created_at=created_at,
            audio=b"pcm",
            recognized_text="x",
            expected_text="x",
            actual_reply="y",
            expected_reply="y",
            latency_ms=1,
            playback_status="COMPLETE",
            error_code=None,
        )

    assert store.purge_expired(datetime.now(UTC)) == ("old",)
    assert [item["test_id"] for item in store.list_records()] == ["current"]


def test_corpus_rejects_symlinked_record_and_audio_paths(tmp_path: Path) -> None:
    root = tmp_path / "voice-corpus"
    store = VoiceTestCorpusStore(root, key_provider=_key)
    store.enable("consent-synthetic-1")
    store.record(
        test_id="test-1",
        session_id="session-1",
        created_at=datetime.now(UTC),
        audio=b"pcm",
        recognized_text="x",
        expected_text="x",
        actual_reply="y",
        expected_reply="y",
        latency_ms=1,
        playback_status="COMPLETE",
        error_code=None,
    )

    record = root / "records" / "test-1.json"
    record_target = tmp_path / "record-target.json"
    record_target.write_bytes(record.read_bytes())
    record.unlink()
    record.symlink_to(record_target)
    with pytest.raises(ValueError, match="voice_test_corpus_unavailable"):
        store.list_records()

    record.unlink()
    record.write_bytes(record_target.read_bytes())
    audio = root / "audio" / "test-1.bin.enc"
    audio_target = tmp_path / "audio-target.bin.enc"
    audio_target.write_bytes(audio.read_bytes())
    audio.unlink()
    audio.symlink_to(audio_target)
    with pytest.raises(ValueError, match="voice_test_corpus_unavailable"):
        store.read_audio("test-1")
