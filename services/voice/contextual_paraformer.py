from __future__ import annotations

import json
import os
import selectors
import signal
import struct
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from services.voice.asr import AsrResult
from services.voice.contextual_artifacts import (
    CONTEXTUAL_BUNDLE_DIGEST,
    validate_contextual_bundle,
)
from tools.voice_contextual_environment import validate_contextual_environment
from tools.voice_contextual_runner import (
    CONTEXTUAL_HOTWORDS,
    CONTEXTUAL_HOTWORDS_SHA256,
)


UNAVAILABLE_REASON = "voice_contextual_unavailable"
INVALID_PCM_REASON = "voice_pcm_invalid"
_MAX_PCM_BYTES = 8 * 16_000 * 2
_MAX_RESPONSE_BYTES = 16_384


class ContextualParaformerProcess:
    """Own one evaluation-only contextual ASR child with bounded framed I/O."""

    def __init__(
        self,
        *,
        project_root: Path,
        environment_validator: Callable[[Path, Path], Path] = validate_contextual_environment,
        artifact_validator: Callable[[Path], Path] = validate_contextual_bundle,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        startup_timeout_seconds: float = 60.0,
        request_timeout_seconds: float = 3.0,
    ) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._closed = False
        self._lock = threading.Lock()
        self._request_timeout = request_timeout_seconds
        try:
            if (
                not 0 < startup_timeout_seconds <= 60
                or not 0 < request_timeout_seconds <= 3
            ):
                raise ValueError(UNAVAILABLE_REASON)
            root = Path(project_root).resolve(strict=True)
            environment = environment_validator(
                root, root / "runtime/voice-contextual-venv"
            )
            bundle = artifact_validator(root)
            runner = root / "tools/voice_contextual_runner.py"
            if runner.is_symlink() or not runner.is_file():
                raise ValueError(UNAVAILABLE_REASON)
            command = (
                str(environment / "bin/python"),
                "-I",
                str(runner),
                "--project-root",
                str(root),
                "--artifact",
                str(bundle),
                "--manifest-sha256",
                CONTEXTUAL_BUNDLE_DIGEST,
                "--expected-prefix",
                str(environment),
            )
            child_environment = {
                "HF_HUB_OFFLINE": "1",
                "NO_PROXY": "*",
                "OMP_NUM_THREADS": "2",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "PYTHONUNBUFFERED": "1",
            }
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
            if self._read_json_line(startup_timeout_seconds, maximum_bytes=128) != {
                "schemaVersion": 1,
                "state": "ready",
            }:
                raise ValueError(UNAVAILABLE_REASON)
        except Exception:
            self._destroy()
            raise ValueError(UNAVAILABLE_REASON) from None

    @property
    def closed(self) -> bool:
        return self._closed

    def transcribe(self, pcm: bytes) -> AsrResult:
        if (
            type(pcm) is not bytes
            or not pcm
            or len(pcm) > _MAX_PCM_BYTES
            or len(pcm) % 2
        ):
            raise ValueError(INVALID_PCM_REASON)
        with self._lock:
            process = self._process
            if self._closed or process is None or process.poll() is not None:
                raise ValueError(UNAVAILABLE_REASON)
            try:
                response = self._exchange(
                    struct.pack(">I", len(pcm)) + pcm,
                    self._request_timeout,
                    maximum_bytes=_MAX_RESPONSE_BYTES,
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
                    return _decode_canonical_json(payload, maximum_bytes)
                if len(payload) > maximum_bytes:
                    raise ValueError(UNAVAILABLE_REASON)
        finally:
            selector.close()

    def _exchange(self, frame: bytes, timeout: float, *, maximum_bytes: int) -> object:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise ValueError(UNAVAILABLE_REASON)
        input_descriptor = process.stdin.fileno()
        output_descriptor = process.stdout.fileno()
        os.set_blocking(input_descriptor, False)
        os.set_blocking(output_descriptor, False)
        selector = selectors.DefaultSelector()
        payload = bytearray()
        sent = 0
        deadline = time.monotonic() + timeout
        try:
            selector.register(input_descriptor, selectors.EVENT_WRITE)
            selector.register(output_descriptor, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                events = selector.select(remaining)
                if not events:
                    raise TimeoutError
                for key, mask in events:
                    if key.fd == input_descriptor and mask & selectors.EVENT_WRITE:
                        try:
                            sent += os.write(input_descriptor, frame[sent:])
                        except BlockingIOError:
                            pass
                        if sent == len(frame):
                            selector.unregister(input_descriptor)
                    if key.fd == output_descriptor and mask & selectors.EVENT_READ:
                        try:
                            chunk = os.read(
                                output_descriptor,
                                min(4096, maximum_bytes + 1 - len(payload)),
                            )
                        except BlockingIOError:
                            continue
                        if not chunk:
                            raise ValueError(UNAVAILABLE_REASON)
                        payload.extend(chunk)
                        newline = payload.find(b"\n")
                        if newline >= 0:
                            if sent != len(frame) or newline != len(payload) - 1:
                                raise ValueError(UNAVAILABLE_REASON)
                            return _decode_canonical_json(payload, maximum_bytes)
                        if len(payload) > maximum_bytes:
                            raise ValueError(UNAVAILABLE_REASON)
        finally:
            selector.close()

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
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
                try:
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _decode_canonical_json(payload: bytearray, maximum_bytes: int) -> object:
    if not payload or len(payload) > maximum_bytes:
        raise ValueError(UNAVAILABLE_REASON)
    decoded = payload.decode("utf-8")
    value = json.loads(decoded)
    canonical = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    if decoded != canonical:
        raise ValueError(UNAVAILABLE_REASON)
    return value


def _validated_response(raw: object) -> AsrResult:
    if not isinstance(raw, dict) or set(raw) != {
        "language",
        "latencyMs",
        "schemaVersion",
        "text",
    }:
        raise ValueError(UNAVAILABLE_REASON)
    latency = raw["latencyMs"]
    text = raw["text"]
    if (
        raw["schemaVersion"] != 1
        or raw["language"] != "zh"
        or type(latency) is not int
        or not 0 <= latency <= 3_000
        or type(text) is not str
        or len(text) > 4_096
        or any(ord(character) < 32 for character in text)
    ):
        raise ValueError(UNAVAILABLE_REASON)
    return AsrResult(text=text, language="zh", duration_ms=latency)


__all__ = [
    "CONTEXTUAL_HOTWORDS",
    "CONTEXTUAL_HOTWORDS_SHA256",
    "ContextualParaformerProcess",
]
