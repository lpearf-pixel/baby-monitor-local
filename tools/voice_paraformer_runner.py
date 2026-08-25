from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO
import stat


SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
MAX_PCM_BYTES = 8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES
Recognizer = Callable[[bytes], str]
_ARTIFACT_ID = "sherpa-onnx-paraformer-zh-2023-09-14"
_SOURCE_REVISION = "def027084691107096b5ebba69785756d63de6c5"
_REQUIRED_FILES = ("model.int8.onnx", "tokens.txt")
_BUNDLE_ERROR = "VOICE_PARAFORMER_BUNDLE_INVALID"
_MAX_MODEL_BYTES = 300 * 1024 * 1024
_MAX_TOKENS_BYTES = 16 * 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024


def run_protocol(
    input_stream: BinaryIO, output_stream: BinaryIO, *, recognizer: Recognizer
) -> int:
    """Serve the fixed framed-PCM protocol without persisting audio or text."""

    try:
        _write_json(output_stream, {"schemaVersion": 1, "state": "ready"})
        while True:
            header = _read_exact(input_stream, 4, allow_eof=True)
            if header is None:
                return 0
            length = struct.unpack(">I", header)[0]
            if not length or length > MAX_PCM_BYTES or length % SAMPLE_WIDTH_BYTES:
                return 1
            pcm = _read_exact(input_stream, length, allow_eof=False)
            if pcm is None:
                return 1
            started = time.monotonic_ns()
            text = recognizer(pcm)
            latency_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
            if (
                type(text) is not str
                or not text
                or len(text) > 4_096
                or any(ord(character) < 32 for character in text)
            ):
                return 1
            _write_json(
                output_stream,
                {
                    "language": "zh",
                    "latencyMs": latency_ms,
                    "schemaVersion": 1,
                    "text": text,
                },
            )
    except Exception:
        return 1


def _read_exact(stream: BinaryIO, size: int, *, allow_eof: bool) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise ValueError("VOICE_PARAFORMER_PROTOCOL_INVALID")
        chunks.extend(chunk)
    return bytes(chunks)


def _write_json(stream: BinaryIO, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    stream.write(payload)
    stream.flush()


def _load_paraformer_recognizer(
    bundle: Path, *, runtime_module: object | None = None
) -> Recognizer:
    import numpy as np

    runtime = runtime_module
    if runtime is None:
        import sherpa_onnx

        runtime = sherpa_onnx
    recognizer = runtime.OfflineRecognizer.from_paraformer(  # type: ignore[attr-defined]
        debug=False,
        decoding_method="greedy_search",
        feature_dim=80,
        num_threads=2,
        paraformer=str(bundle / "model.int8.onnx"),
        sample_rate=SAMPLE_RATE_HZ,
        tokens=str(bundle / "tokens.txt"),
    )

    def recognize(pcm: bytes) -> str:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        stream = recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE_HZ, samples)
        recognizer.decode_stream(stream)
        return stream.result.text

    return recognize


def _validate_paraformer_bundle(bundle: Path, manifest_sha256: str) -> Path:
    try:
        if not _is_sha256(manifest_sha256) or bundle.is_symlink():
            raise ValueError(_BUNDLE_ERROR)
        checked = bundle.resolve(strict=True)
        if not checked.is_dir():
            raise ValueError(_BUNDLE_ERROR)
        actual = set()
        for entry in checked.rglob("*"):
            if entry.is_symlink():
                raise ValueError(_BUNDLE_ERROR)
            if entry.is_file():
                actual.add(entry.relative_to(checked).as_posix())
            elif not entry.is_dir():
                raise ValueError(_BUNDLE_ERROR)
        if actual != {"manifest.json", *_REQUIRED_FILES}:
            raise ValueError(_BUNDLE_ERROR)
        manifest_bytes = (checked / "manifest.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
            raise ValueError(_BUNDLE_ERROR)
        manifest = json.loads(manifest_bytes.decode("ascii"))
        if (
            not isinstance(manifest, dict)
            or manifest_bytes
            != (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "ascii"
            )
            or set(manifest)
            != {
                "artifact_id",
                "files",
                "source_manifest_sha256",
                "source_revision",
                "spdx_license",
            }
            or manifest["artifact_id"] != _ARTIFACT_ID
            or manifest["source_revision"] != _SOURCE_REVISION
            or manifest["spdx_license"] != "Apache-2.0"
            or not _is_sha256(manifest["source_manifest_sha256"])
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != set(_REQUIRED_FILES)
        ):
            raise ValueError(_BUNDLE_ERROR)
        for filename in _REQUIRED_FILES:
            expected = manifest["files"][filename]
            if not _is_sha256(expected) or _sha256_file(checked / filename) != expected:
                raise ValueError(_BUNDLE_ERROR)
        return checked
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise ValueError(_BUNDLE_ERROR) from None


@contextmanager
def _verified_bundle_snapshot(bundle: Path, manifest_sha256: str):
    """Yield a child-private verified copy so later path replacement cannot alter use."""

    directory_descriptor = -1
    try:
        if not _is_sha256(manifest_sha256) or bundle.is_symlink():
            raise ValueError(_BUNDLE_ERROR)
        checked = bundle.resolve(strict=True)
        directory_descriptor = os.open(
            checked,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        if set(os.listdir(directory_descriptor)) != {"manifest.json", *_REQUIRED_FILES}:
            raise ValueError(_BUNDLE_ERROR)
        with tempfile.TemporaryDirectory(prefix="voice-paraformer-snapshot-") as name:
            snapshot = Path(name) / "bundle"
            snapshot.mkdir(mode=0o700)
            _copy_regular_at(
                directory_descriptor,
                "manifest.json",
                snapshot / "manifest.json",
                _MAX_MANIFEST_BYTES,
            )
            manifest_bytes = (snapshot / "manifest.json").read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
                raise ValueError(_BUNDLE_ERROR)
            manifest = json.loads(manifest_bytes.decode("ascii"))
            if (
                not isinstance(manifest, dict)
                or manifest_bytes
                != (
                    json.dumps(manifest, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode("ascii")
                or set(manifest)
                != {
                    "artifact_id",
                    "files",
                    "source_manifest_sha256",
                    "source_revision",
                    "spdx_license",
                }
                or manifest["artifact_id"] != _ARTIFACT_ID
                or manifest["source_revision"] != _SOURCE_REVISION
                or manifest["spdx_license"] != "Apache-2.0"
                or not _is_sha256(manifest["source_manifest_sha256"])
                or not isinstance(manifest["files"], dict)
                or set(manifest["files"]) != set(_REQUIRED_FILES)
            ):
                raise ValueError(_BUNDLE_ERROR)
            limits = {
                "model.int8.onnx": _MAX_MODEL_BYTES,
                "tokens.txt": _MAX_TOKENS_BYTES,
            }
            for filename in _REQUIRED_FILES:
                digest = _copy_regular_at(
                    directory_descriptor,
                    filename,
                    snapshot / filename,
                    limits[filename],
                )
                if not _is_sha256(manifest["files"][filename]) or digest != manifest[
                    "files"
                ][filename]:
                    raise ValueError(_BUNDLE_ERROR)
            yield snapshot
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise ValueError(_BUNDLE_ERROR) from None
    finally:
        if directory_descriptor >= 0:
            os.close(directory_descriptor)


def _copy_regular_at(
    directory_descriptor: int, filename: str, target: Path, maximum_bytes: int
) -> str:
    descriptor = os.open(
        filename,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=directory_descriptor,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum_bytes:
            raise ValueError(_BUNDLE_ERROR)
        hasher = hashlib.sha256()
        total = 0
        with target.open("xb") as output:
            target.chmod(0o600)
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise ValueError(_BUNDLE_ERROR)
                hasher.update(chunk)
                output.write(chunk)
        if total != metadata.st_size:
            raise ValueError(_BUNDLE_ERROR)
        return hasher.hexdigest()
    finally:
        os.close(descriptor)


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline local Paraformer adapter")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-prefix", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if (
            Path(sys.prefix).resolve(strict=True)
            != arguments.expected_prefix.resolve(strict=True)
        ):
            return 1
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["NO_PROXY"] = "*"
        with _verified_bundle_snapshot(
            arguments.artifact, arguments.manifest_sha256
        ) as bundle:
            recognizer = _load_paraformer_recognizer(bundle)
            return run_protocol(
                sys.stdin.buffer, sys.stdout.buffer, recognizer=recognizer
            )
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
