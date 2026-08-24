from __future__ import annotations

import argparse
import math
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.ecapa import EcapaEmbedding, EcapaProcess


UNAVAILABLE_REASON = "voice_model_unavailable"
SAMPLE_COUNT = 5
EMBEDDING_DIMENSIONS = 192
MAX_LATENCY_MS = 3_000
_PHRASES = (
    "小小，我是爸爸",
    "小小，我是妈妈",
    "小小，我要开始喂奶",
    "小小，我喂完奶了",
    "小小，我要结束喂奶",
)


class _EmbeddingProcess(Protocol):
    def embed(self, pcm: bytes) -> EcapaEmbedding: ...

    def close(self) -> None: ...


Synthesizer = Callable[[str, Path], None]
Decoder = Callable[[Path], bytes]
ProcessFactory = Callable[..., _EmbeddingProcess]


@dataclass(frozen=True)
class ProbeReport:
    result: Literal["PASS"]
    sample_count: int
    dimensions: int
    normalized_count: int
    latency_p50_ms: int
    latency_p95_ms: int
    raw_audio_persisted: Literal[False]


def run_ecapa_probe(
    *,
    project_root: Path,
    settings_path: Path,
    synthesizer: Synthesizer | None = None,
    decoder: Decoder | None = None,
    process_factory: ProcessFactory = EcapaProcess,
    temporary_parent: Path | None = None,
) -> ProbeReport:
    """Run five generated utterances through one local ECAPA child."""

    process: _EmbeddingProcess | None = None
    try:
        synthesizer = synthesizer or synthesize_generated_wave
        decoder = decoder or decode_generated_wave
        root = project_root.resolve(strict=True)
        if settings_path.is_symlink() or not settings_path.is_file():
            raise ValueError(UNAVAILABLE_REASON)
        settings = VoiceCareSettings.model_validate_json(
            settings_path.read_text(encoding="ascii")
        )
        if settings.enabled:
            raise ValueError(UNAVAILABLE_REASON)
        spec = voice_artifact_spec(settings, "speechbrain-ecapa-voxceleb")
        samples: list[bytes] = []
        with tempfile.TemporaryDirectory(
            prefix="voice-ecapa-probe-", dir=temporary_parent
        ) as temporary:
            temporary_root = Path(temporary)
            temporary_root.chmod(0o700)
            for index, phrase in enumerate(_PHRASES):
                wave_path = temporary_root / f"generated-{index}.aiff"
                try:
                    synthesizer(phrase, wave_path)
                    pcm = decoder(wave_path)
                finally:
                    if wave_path.exists() and not wave_path.is_symlink():
                        wave_path.unlink()
                samples.append(pcm)
        process = process_factory(spec, project_root=root)
        latencies: list[int] = []
        normalized = 0
        for index, pcm in enumerate(samples):
            try:
                result = process.embed(pcm)
                if not _valid_embedding(result):
                    raise ValueError(UNAVAILABLE_REASON)
                normalized += 1
                latencies.append(result.latency_ms)
            finally:
                samples[index] = b""
        p50 = _nearest_rank(latencies, 0.50)
        p95 = _nearest_rank(latencies, 0.95)
        if normalized != SAMPLE_COUNT or p95 > MAX_LATENCY_MS:
            raise ValueError(UNAVAILABLE_REASON)
        return ProbeReport("PASS", SAMPLE_COUNT, EMBEDDING_DIMENSIONS, normalized, p50, p95, False)
    except Exception:
        raise ValueError(UNAVAILABLE_REASON) from None
    finally:
        if process is not None:
            process.close()


def synthesize_generated_wave(text: str, destination: Path) -> None:
    command = (
        "say",
        "--voice=Tingting",
        "--rate=170",
        "--file-format=AIFF",
        f"--output-file={destination}",
        text,
    )
    for attempt in range(3):
        if destination.is_symlink():
            raise ValueError(UNAVAILABLE_REASON)
        if destination.exists():
            destination.unlink()
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            env=_media_tool_environment(),
        )
        if _generated_audio_complete(destination):
            return
        if attempt < 2:
            time.sleep(0.05)
    raise ValueError(UNAVAILABLE_REASON)


def _generated_audio_complete(destination: Path) -> bool:
    try:
        if destination.is_symlink() or not destination.is_file():
            return False
        return 4_096 < destination.stat().st_size <= 10 * 1024 * 1024
    except OSError:
        return False


def decode_generated_wave(source: Path) -> bytes:
    command = (
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
    for attempt in range(3):
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=20,
            env=_media_tool_environment(),
        )
        pcm = result.stdout
        if (
            result.returncode == 0
            and type(pcm) is bytes
            and int(0.8 * 16_000 * 2) <= len(pcm) <= 8 * 16_000 * 2
            and len(pcm) % 2 == 0
        ):
            return pcm
        if result.returncode == 0 and pcm == b"" and attempt < 2:
            time.sleep(0.05)
            continue
        break
    raise ValueError(UNAVAILABLE_REASON)


def _media_tool_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS"):
        environment.pop(name, None)
    return environment


def print_report(report: ProbeReport) -> None:
    print(f"result={report.result}")
    print(f"sample_count={report.sample_count}")
    print(f"dimensions={report.dimensions}")
    print(f"normalized_count={report.normalized_count}")
    print(f"latency_p50_ms={report.latency_p50_ms}")
    print(f"latency_p95_ms={report.latency_p95_ms}")
    print("raw_audio_persisted=false")


def _valid_embedding(result: object) -> bool:
    if (
        not isinstance(result, EcapaEmbedding)
        or len(result.embedding) != EMBEDDING_DIMENSIONS
        or type(result.latency_ms) is not int
        or not 0 <= result.latency_ms <= 5_000
        or any(not math.isfinite(value) for value in result.embedding)
    ):
        return False
    norm = math.sqrt(sum(value * value for value in result.embedding))
    return math.isfinite(norm) and 0.999 <= norm <= 1.001


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def _interrupt(_signal_number: int, _frame: object) -> None:
    raise InterruptedError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the generated local ECAPA gate")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("runtime/config/voice-care-models.json"),
    )
    arguments = parser.parse_args(argv)
    previous = {
        signal_number: signal.signal(signal_number, _interrupt)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        report = run_ecapa_probe(
            project_root=Path.cwd(),
            settings_path=arguments.settings,
            synthesizer=synthesize_generated_wave,
            decoder=decode_generated_wave,
        )
        print_report(report)
        return 0
    except Exception:
        print("result=FAIL")
        print(f"reason={UNAVAILABLE_REASON}")
        print("raw_audio_persisted=false")
        return 1
    finally:
        for signal_number, handler in previous.items():
            signal.signal(signal_number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
