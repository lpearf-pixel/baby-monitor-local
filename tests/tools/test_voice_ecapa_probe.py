from __future__ import annotations

import json
import os
import subprocess
import wave
from pathlib import Path

import pytest

from services.voice.ecapa import EcapaEmbedding
from tools import voice_ecapa_probe as probe
from tools.voice_ecapa_probe import ProbeReport, run_ecapa_probe


PCM = b"\x01\x00" * (16_000 * 2)
EMBEDDING = tuple([1.0] + [0.0] * 191)


def _write_generated_wave(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x01\x00" * 16_000)


class _Process:
    def __init__(self, latencies: list[int]) -> None:
        self._latencies = iter(latencies)
        self.pcm: list[bytes] = []
        self.closed = False

    def embed(self, pcm: bytes) -> EcapaEmbedding:
        self.pcm.append(pcm)
        return EcapaEmbedding(EMBEDDING, next(self._latencies))

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path: Path) -> Path:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "enabled": False,
                "speechbrain_ecapa_manifest_sha256": "4" * 64,
            }
        ),
        encoding="ascii",
    )
    return settings


def test_probe_reuses_one_process_for_five_generated_samples_and_cleans_up(
    tmp_path: Path,
) -> None:
    process = _Process([5, 1, 4, 2, 3])
    synthesized: list[str] = []
    factories: list[object] = []

    def synthesize(text: str, destination: Path) -> None:
        synthesized.append(text)
        destination.write_bytes(b"synthetic generated wave")

    def decoder(source: Path) -> bytes:
        assert source.is_file()
        return PCM

    def process_factory(*_args: object, **_kwargs: object) -> _Process:
        assert len(synthesized) == 5
        factories.append(object())
        return process

    report = run_ecapa_probe(
        project_root=tmp_path,
        settings_path=_settings(tmp_path),
        synthesizer=synthesize,
        decoder=decoder,
        process_factory=process_factory,
        temporary_parent=tmp_path,
    )

    assert report == ProbeReport(
        result="PASS",
        sample_count=5,
        dimensions=192,
        normalized_count=5,
        latency_p50_ms=3,
        latency_p95_ms=5,
        raw_audio_persisted=False,
    )
    assert len(synthesized) == 5
    assert len(factories) == 1
    assert process.pcm == [PCM] * 5
    assert process.closed is True
    assert list(tmp_path.glob("voice-ecapa-probe-*")) == []


def test_probe_cleans_up_and_redacts_a_dependency_failure(tmp_path: Path) -> None:
    process = _Process([1] * 5)

    def synthesize(_text: str, destination: Path) -> None:
        destination.write_bytes(b"synthetic generated wave")
        raise RuntimeError("private path and transcript")

    with pytest.raises(ValueError, match="^voice_model_unavailable$") as error:
        run_ecapa_probe(
            project_root=tmp_path,
            settings_path=_settings(tmp_path),
            synthesizer=synthesize,
            decoder=lambda _source: PCM,
            process_factory=lambda *_args, **_kwargs: process,
            temporary_parent=tmp_path,
        )

    assert "private" not in str(error.value)
    assert process.closed is False
    assert list(tmp_path.glob("voice-ecapa-probe-*")) == []


def test_probe_output_is_aggregate_only(capsys: pytest.CaptureFixture[str]) -> None:
    report = ProbeReport("PASS", 5, 192, 5, 12, 20, False)

    probe.print_report(report)

    output = capsys.readouterr().out
    assert output.splitlines() == [
        "result=PASS",
        "sample_count=5",
        "dimensions=192",
        "normalized_count=5",
        "latency_p50_ms=12",
        "latency_p95_ms=20",
        "raw_audio_persisted=false",
    ]
    for forbidden in ("爸爸", "妈妈", "/", "embedding", "Tingting"):
        assert forbidden not in output


def test_probe_decoder_uses_fixed_memory_only_ffmpeg_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "generated.wav"
    source.write_bytes(b"synthetic")
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **options: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        assert options["capture_output"] is True
        return subprocess.CompletedProcess(command, 0, stdout=PCM, stderr=b"")

    monkeypatch.setattr(probe.subprocess, "run", run)

    assert probe.decode_generated_wave(source) == PCM
    assert commands == [
        (
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "16000",
            "pipe:1",
        )
    ]


def test_probe_decoder_retries_only_a_successful_empty_async_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "generated.wav"
    source.write_bytes(b"synthetic")
    outputs = iter((b"", PCM))
    attempts: list[int] = []
    sleeps: list[float] = []

    def run(command: tuple[str, ...], **_options: object) -> subprocess.CompletedProcess[bytes]:
        attempts.append(1)
        return subprocess.CompletedProcess(
            command, 0, stdout=next(outputs), stderr=b""
        )

    monkeypatch.setattr(probe.subprocess, "run", run)
    monkeypatch.setattr(probe.time, "sleep", sleeps.append)

    assert probe.decode_generated_wave(source) == PCM
    assert len(attempts) == 2
    assert sleeps == [0.05]


def test_probe_decoder_bounds_an_always_empty_async_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "generated.wav"
    source.write_bytes(b"synthetic")
    attempts: list[int] = []
    sleeps: list[float] = []

    def run(command: tuple[str, ...], **_options: object) -> subprocess.CompletedProcess[bytes]:
        attempts.append(1)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(probe.subprocess, "run", run)
    monkeypatch.setattr(probe.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        probe.decode_generated_wave(source)
    assert len(attempts) == 3
    assert sleeps == [0.05] * 2


def test_probe_synthesizer_uses_the_stable_native_aiff_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "generated.wav"
    commands: list[tuple[str, ...]] = []
    options: list[dict[str, object]] = []
    for name in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS"):
        monkeypatch.setenv(name, "synthetic-make-state")

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        options.append(kwargs)
        _write_generated_wave(destination)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(probe.subprocess, "run", run)

    probe.synthesize_generated_wave("synthetic phrase", destination)

    assert commands == [
        (
            "say",
            "--voice=Tingting",
            "--rate=170",
            "--file-format=AIFF",
            f"--output-file={destination}",
            "synthetic phrase",
        )
    ]
    child_environment = options[0]["env"]
    assert isinstance(child_environment, dict)
    assert child_environment.get("PATH") == os.environ.get("PATH")
    assert not {"MAKEFLAGS", "MAKELEVEL", "MFLAGS"} & set(child_environment)


def test_probe_synthesizer_retries_a_truncated_generated_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "generated.wav"
    attempts: list[int] = []
    sleeps: list[float] = []

    def run(command: tuple[str, ...], **_options: object) -> subprocess.CompletedProcess[bytes]:
        attempts.append(1)
        if len(attempts) == 1:
            destination.write_bytes(b"RIFF" + b"\x00" * 4092)
        else:
            _write_generated_wave(destination)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(probe.subprocess, "run", run)
    monkeypatch.setattr(probe.time, "sleep", sleeps.append)

    probe.synthesize_generated_wave("synthetic phrase", destination)

    assert len(attempts) == 2
    assert sleeps == [0.05]
    with wave.open(str(destination), "rb") as generated:
        assert generated.getnframes() == 16_000
