from __future__ import annotations

import json
import math
import os
import selectors
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.voice.artifacts import VoiceArtifactSpec, validate_voice_artifact
from tools.voice_speaker_environment import validate_speaker_environment


SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
MIN_PCM_BYTES = int(0.8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES)
MAX_PCM_BYTES = 8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES
EMBEDDING_DIMENSIONS = 192
UNAVAILABLE_REASON = "voice_model_unavailable"
INVALID_PCM_REASON = "voice_pcm_invalid"
_MAX_RESPONSE_BYTES = 8_192


@dataclass(frozen=True)
class EcapaEmbedding:
    embedding: tuple[float, ...]
    latency_ms: int


class EcapaProcess:
    """Own one bounded offline ECAPA subprocess and its framed in-memory PCM pipe."""

    def __init__(
        self,
        artifact: VoiceArtifactSpec,
        *,
        project_root: Path,
        environment_validator: Callable[..., Path] = validate_speaker_environment,
        artifact_validator: Callable[[VoiceArtifactSpec, Path], Path] = validate_voice_artifact,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        startup_timeout_seconds: float = 60.0,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._request_timeout = request_timeout_seconds
        try:
            if (
                artifact.artifact_id != "speechbrain-ecapa-voxceleb"
                or not 0 < startup_timeout_seconds <= 60
                or not 0 < request_timeout_seconds <= 5
            ):
                raise ValueError(UNAVAILABLE_REASON)
            root = project_root.resolve(strict=True)
            expected_environment = root / "runtime/voice-speaker-venv"
            environment = environment_validator(root, expected_environment)
            bundle = artifact_validator(artifact, root)
            runner = root / "tools/voice_ecapa_runner.py"
            if runner.is_symlink() or not runner.is_file():
                raise ValueError(UNAVAILABLE_REASON)
            command = (
                str(environment / "bin/python"),
                "-m",
                "tools.voice_ecapa_runner",
                "--artifact",
                str(bundle),
                "--manifest-sha256",
                artifact.manifest_sha256,
                "--expected-prefix",
                str(environment),
            )
            child_environment = {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "NO_PROXY": "*",
                "PYTHONUNBUFFERED": "1",
            }
            if "PATH" in os.environ:
                child_environment["PATH"] = os.environ["PATH"]
            self._process = popen_factory(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=child_environment,
                bufsize=0,
                start_new_session=True,
                cwd=str(root),
            )
            ready = self._read_json_line(startup_timeout_seconds, maximum_bytes=128)
            if ready != {"schemaVersion": 1, "state": "ready"}:
                raise ValueError(UNAVAILABLE_REASON)
        except Exception:
            self._destroy()
            raise ValueError(UNAVAILABLE_REASON) from None

    @property
    def closed(self) -> bool:
        return self._closed

    def embed(self, pcm: bytes) -> EcapaEmbedding:
        if (
            type(pcm) is not bytes
            or len(pcm) < MIN_PCM_BYTES
            or len(pcm) > MAX_PCM_BYTES
            or len(pcm) % SAMPLE_WIDTH_BYTES
        ):
            raise ValueError(INVALID_PCM_REASON)
        with self._lock:
            process = self._process
            if self._closed or process is None or process.poll() is not None:
                raise ValueError(UNAVAILABLE_REASON)
            try:
                if process.stdin is None:
                    raise ValueError(UNAVAILABLE_REASON)
                process.stdin.write(struct.pack(">I", len(pcm)))
                process.stdin.write(pcm)
                process.stdin.flush()
                response = self._read_json_line(
                    self._request_timeout, maximum_bytes=_MAX_RESPONSE_BYTES
                )
                return _validated_response(response)
            except Exception:
                self._destroy()
                raise ValueError(UNAVAILABLE_REASON) from None

    def close(self) -> None:
        with self._lock:
            self._destroy()

    def _read_json_line(self, timeout: float, *, maximum_bytes: int) -> object:
        process = self._process
        if process is None or process.stdout is None:
            raise ValueError(UNAVAILABLE_REASON)
        descriptor = process.stdout.fileno()
        selector = selectors.DefaultSelector()
        payload = bytearray()
        deadline = time.monotonic() + timeout
        try:
            selector.register(descriptor, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise TimeoutError
                chunk = os.read(descriptor, min(4096, maximum_bytes + 1 - len(payload)))
                if not chunk:
                    raise ValueError(UNAVAILABLE_REASON)
                payload.extend(chunk)
                newline = payload.find(b"\n")
                if newline >= 0:
                    if newline != len(payload) - 1:
                        raise ValueError(UNAVAILABLE_REASON)
                    break
                if len(payload) > maximum_bytes:
                    raise ValueError(UNAVAILABLE_REASON)
        finally:
            selector.close()
        if not payload or len(payload) > maximum_bytes:
            raise ValueError(UNAVAILABLE_REASON)
        decoded = payload.decode("ascii")
        value = json.loads(decoded)
        canonical = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        if decoded != canonical:
            raise ValueError(UNAVAILABLE_REASON)
        return value

    def _destroy(self) -> None:
        process = self._process
        self._process = None
        self._closed = True
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _validated_response(raw: object) -> EcapaEmbedding:
    if not isinstance(raw, dict) or set(raw) != {
        "embedding",
        "latencyMs",
        "schemaVersion",
    }:
        raise ValueError(UNAVAILABLE_REASON)
    embedding = raw["embedding"]
    latency = raw["latencyMs"]
    if (
        raw["schemaVersion"] != 1
        or type(latency) is not int
        or not 0 <= latency <= 5_000
        or type(embedding) is not list
        or len(embedding) != EMBEDDING_DIMENSIONS
        or any(
            type(value) not in {int, float} or not math.isfinite(value)
            for value in embedding
        )
    ):
        raise ValueError(UNAVAILABLE_REASON)
    values = tuple(float(value) for value in embedding)
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or not 0.999 <= norm <= 1.001:
        raise ValueError(UNAVAILABLE_REASON)
    return EcapaEmbedding(values, latency)


__all__ = ["EcapaEmbedding", "EcapaProcess"]
