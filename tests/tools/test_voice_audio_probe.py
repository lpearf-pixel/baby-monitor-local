from __future__ import annotations

import pytest

from services.audio.feasibility import (
    AudioFeasibilityError,
    AudioMediaResult,
    AudioReadinessResult,
    AudioReceiveResult,
    SyntheticOpusResult,
)
from tools import voice_audio_probe


def test_live_cli_prints_only_bounded_media_and_receive_metrics(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        voice_audio_probe,
        "inspect_audio_media",
        lambda: AudioMediaResult("hevc", "opus", "opus", 16_000, 1),
    )
    monkeypatch.setattr(
        voice_audio_probe,
        "receive_audio_window",
        lambda **_kwargs: AudioReceiveResult(60.0, 1_920_000, 60),
    )

    result = voice_audio_probe.main(["live", "--duration", "60"])

    output = capsys.readouterr().out
    assert result == 0
    assert output.splitlines() == [
        "result=PASS",
        "source_video_codec=hevc",
        "source_audio_codec=opus",
        "alias_audio_codec=opus",
        "sample_rate_hz=16000",
        "channels=1",
        "duration_seconds=60",
        "decoded_seconds=60.000",
        "decoded_bytes=1920000",
        "chunk_count=60",
        "raw_audio_persisted=false",
    ]


def test_cli_failure_prints_only_stable_reason(monkeypatch, capsys) -> None:
    def fail() -> AudioMediaResult:
        raise AudioFeasibilityError("audio_alias_unsupported")

    monkeypatch.setattr(voice_audio_probe, "inspect_audio_media", fail)

    result = voice_audio_probe.main(["media"])

    output = capsys.readouterr().out
    assert result == 2
    assert output == "result=FAIL\nreason=audio_alias_unsupported\n"


def test_live_cli_does_not_print_partial_pass_before_decode_failure(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        voice_audio_probe,
        "inspect_audio_media",
        lambda: AudioMediaResult("hevc", "opus", "opus", 48_000, 2),
    )

    def fail(**_kwargs) -> AudioReceiveResult:
        raise AudioFeasibilityError("audio_decode_failed")

    monkeypatch.setattr(voice_audio_probe, "receive_audio_window", fail)

    result = voice_audio_probe.main(["live", "--duration", "60"])

    assert result == 2
    assert capsys.readouterr().out == (
        "result=FAIL\nreason=audio_decode_failed\n"
    )


def test_synthetic_cli_reports_counts_without_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        voice_audio_probe,
        "verify_synthetic_opus",
        lambda: SyntheticOpusResult(1_234, 32_000, 1.0),
    )

    result = voice_audio_probe.main(["synthetic"])

    assert result == 0
    assert capsys.readouterr().out.splitlines() == [
        "result=PASS",
        "codec=opus",
        "sample_rate_hz=16000",
        "channels=1",
        "opus_bytes=1234",
        "pcm_bytes=32000",
        "decoded_seconds=1.000",
        "raw_audio_persisted=false",
    ]


def test_chain_cli_prints_only_fixed_aggregate_stages(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        voice_audio_probe,
        "probe_audio_readiness",
        lambda: AudioReadinessResult(True, True, True, True, True, False),
    )

    result = voice_audio_probe.main(["chain"])

    assert result == 0
    assert capsys.readouterr().out.splitlines() == [
        "result=PASS",
        "camera_audio_media_available=true",
        "opus_48000_stereo_available=true",
        "pcm_decode_available=true",
        "vad_progression_available=true",
        "asr_runtime_available=true",
        "raw_audio_persisted=false",
    ]


def test_chain_cli_redacts_runtime_failure(monkeypatch, capsys) -> None:
    def fail() -> AudioReadinessResult:
        raise AudioFeasibilityError("asr_runtime_unavailable")

    monkeypatch.setattr(voice_audio_probe, "probe_audio_readiness", fail)

    assert voice_audio_probe.main(["chain"]) == 2
    assert capsys.readouterr().out == (
        "result=FAIL\nreason=asr_runtime_unavailable\n"
    )


def test_chain_probe_stops_before_asr_when_vad_progression_is_invalid(
    tmp_path,
) -> None:
    calls: list[str] = []

    with pytest.raises(AudioFeasibilityError, match="vad_progression_unavailable"):
        voice_audio_probe.probe_audio_readiness(
            project_root=tmp_path,
            media_inspector=lambda: AudioMediaResult(
                "hevc", "opus", "opus", 48_000, 2
            ),
            receiver=lambda: AudioReceiveResult(1.0, 32_000, 1),
            vad_probe=lambda _root: (False, False, False),
            asr_probe=lambda _root: calls.append("asr") or True,
        )

    assert calls == []
