#!/usr/bin/env python3
"""Bounded local-only tooling for the private visual corpus overlay."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.contracts.private_visual_overlay import (  # noqa: E402
    LocalOverlayReadiness,
    PrivateVisualOverlayError,
    load_private_overlay_descriptor,
)
from packages.contracts.settings import AppSettings  # noqa: E402
from packages.monitoring.xiaomi_media_diagnostic import (  # noqa: E402
    XiaomiMediaDiagnosticError,
)
from services.vision.private_visual_overlay import (  # noqa: E402
    PrivateMediaFacts,
    PrivateOverlayValidation,
    local_overlay_status,
    review_complete_for_asset,
    validate_private_overlay,
)
from services.vision.corpus_manifest import load_manifest  # noqa: E402
from services.voice.camera_reply import parse_source_media  # noqa: E402
from tools.xiaomi_media_diagnostic import collect_snapshot  # noqa: E402


FFMPEG_EXECUTABLE = "ffmpeg"
FFPROBE_EXECUTABLE = "ffprobe"
_SOURCE_ALIAS = "rtsp://127.0.0.1:8554/source"
_SOURCE_STATUS_URL = "http://127.0.0.1:1984/api/streams?src=source"
_PRIVATE_RELATIVE = Path("runtime/test-corpus/visual/private-overlay")
_DESCRIPTOR_RELATIVE = Path("tests/fixtures/visual_corpus/private_overlay.json")
_PUBLIC_MANIFEST_RELATIVE = Path("tests/fixtures/visual_corpus/manifest.json")
_REQUIRED_LOCAL_SCENARIOS = ("WIDE-02", "NEG-01")
_DURATIONS = (20, 25, 30)
_MAX_MEDIA_BYTES = 128 * 1024 * 1024
_MAX_INDEX_BYTES = 64 * 1024
_MAX_PROBE_BYTES = 64 * 1024
_PROBE_TIMEOUT_SECONDS = 10.0
_PROCESS_GRACE_SECONDS = 2.0
_SOURCE_TIMEOUT_SECONDS = 2.0
_PRIVATE_ID = re.compile(r"^plc-[0-9a-f]{32}$")
_SAFE_REASONS = frozenset(
    {
        "private_overlay_metadata_invalid",
        "private_overlay_forbidden_locator",
        "private_overlay_unavailable",
        "private_overlay_mapping_invalid",
        "private_overlay_permissions_invalid",
        "private_overlay_identity_mismatch",
        "private_overlay_media_invalid",
        "private_overlay_audio_present",
        "private_overlay_review_incomplete",
        "private_overlay_scenario_invalid",
        "private_overlay_duplicate_clip",
        "private_overlay_capture_precondition_failed",
    }
)


class PrivateVisualCorpusError(RuntimeError):
    """Stable, redacted private-corpus command failure."""


@dataclass(frozen=True, slots=True)
class CapturePreflight:
    camera_reply_enabled: bool
    speaker_state: str
    pending_command_responses: int
    residual_sender_count: int
    configured_transport: str
    producer_count: int
    negotiated_protocol: str
    producer_generation: int
    consumer_count: int
    video_media_ready: bool
    video_bytes_increased: bool = True
    producer_replaced: bool = False


@dataclass(frozen=True, slots=True)
class CaptureResult:
    private_asset_id: str
    bytes: int
    sha256: str
    duration_ms: int
    codec: str
    width: int
    height: int
    fps: float
    video_streams: int
    audio_streams: int
    subtitle_streams: int
    data_streams: int


@dataclass(frozen=True, slots=True)
class ReviewPreparation:
    private_asset_id: str
    sha256: str
    sample_interval_ms: int
    sample_frame_count: int
    first_frame_present: bool
    last_frame_present: bool


@dataclass(frozen=True, slots=True)
class ReviewStatus:
    private_asset_id: str
    state: str


CaptureRunner = Callable[[tuple[str, ...], float], None]
CaptureProbe = Callable[[Path], PrivateMediaFacts]
PreflightCollector = Callable[[], CapturePreflight]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def parser() -> argparse.ArgumentParser:
    command = _RedactedArgumentParser(
        description="Operate the fixed private visual corpus overlay"
    )
    subcommands = command.add_subparsers(
        dest="command",
        required=True,
        parser_class=_RedactedArgumentParser,
    )
    subcommands.add_parser("validate")
    subcommands.add_parser("capture-preflight")
    capture = subcommands.add_parser("capture")
    capture.add_argument("--duration", type=int, choices=_DURATIONS, required=True)
    review = subcommands.add_parser("review-prepare")
    review.add_argument("--private-asset-id", type=_parse_asset_id, required=True)
    status = subcommands.add_parser("review-status")
    status.add_argument("--private-asset-id", type=_parse_asset_id, required=True)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "validate":
            return _validate_command(REPOSITORY_ROOT)
        if arguments.command == "capture-preflight":
            preflight = _collect_capture_preflight(REPOSITORY_ROOT)
            _validate_preflight(preflight)
            _emit(result="PASS", operation="capture-preflight", reason="ok")
            return 0
        if arguments.command == "capture":
            before = _collect_capture_preflight(REPOSITORY_ROOT)
            result = capture_private_asset(
                REPOSITORY_ROOT,
                arguments.duration,
                preflight=before,
                postflight=lambda: _collect_capture_preflight(REPOSITORY_ROOT),
            )
            _emit_capture(result)
            return 0
        if arguments.command == "review-prepare":
            result = prepare_review_material(
                REPOSITORY_ROOT,
                arguments.private_asset_id,
            )
            _emit(
                result="PASS",
                operation="review-prepare",
                private_asset_id=result.private_asset_id,
                sha256=result.sha256,
                sample_interval_ms=result.sample_interval_ms,
                sample_frame_count=result.sample_frame_count,
                first_frame_present=str(result.first_frame_present).lower(),
                last_frame_present=str(result.last_frame_present).lower(),
            )
            return 0
        if arguments.command == "review-status":
            result = review_status(REPOSITORY_ROOT, arguments.private_asset_id)
            _emit(
                result="PASS",
                operation="review-status",
                private_asset_id=result.private_asset_id,
                review_state=result.state,
            )
            return 0
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")
    except KeyboardInterrupt:
        _emit(
            result="FAIL",
            operation=arguments.command,
            reason="private_overlay_capture_precondition_failed",
        )
        return 130
    except (PrivateVisualCorpusError, PrivateVisualOverlayError) as exc:
        reason = str(exc)
        if reason not in _SAFE_REASONS:
            reason = "private_overlay_capture_precondition_failed"
        _emit(result="FAIL", operation=arguments.command, reason=reason)
        return 2
    except Exception:
        _emit(
            result="FAIL",
            operation=arguments.command,
            reason="private_overlay_capture_precondition_failed",
        )
        return 2


def capture_private_asset(
    repository: Path,
    duration: int,
    *,
    preflight: CapturePreflight,
    postflight: PreflightCollector,
    runner: CaptureRunner | None = None,
    probe: CaptureProbe | None = None,
    asset_id_factory: Callable[[], str] | None = None,
) -> CaptureResult:
    _validate_preflight(preflight)
    if type(duration) is not int or duration not in _DURATIONS:
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")
    selected_runner = runner or _run_ffmpeg
    selected_probe = probe or probe_private_media
    selected_id_factory = asset_id_factory or _asset_id
    private_asset_id = selected_id_factory()
    if type(private_asset_id) is not str or _PRIVATE_ID.fullmatch(private_asset_id) is None:
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")

    overlay = _prepare_overlay_layout(Path(repository))
    with _capture_lock(overlay / "temp" / "capture.lock"):
        mapping = _load_index(overlay)
        basename = f"{private_asset_id}.mkv"
        if (
            private_asset_id in mapping
            or basename in mapping.values()
            or (overlay / "assets" / basename).exists()
        ):
            raise PrivateVisualCorpusError("private_overlay_duplicate_clip")
        if len(mapping) >= 20:
            raise PrivateVisualCorpusError("private_overlay_duplicate_clip")
        _require_asset_inventory(overlay / "assets", mapping)

        descriptor, raw_temporary = tempfile.mkstemp(
            prefix=f".{private_asset_id}-",
            suffix=".tmp",
            dir=overlay / "temp",
        )
        temporary = Path(raw_temporary)
        os.fchmod(descriptor, 0o600)
        initial = os.fstat(descriptor)
        os.close(descriptor)
        final = overlay / "assets" / basename
        published = False
        try:
            argv = _ffmpeg_argv(duration, temporary)
            try:
                selected_runner(argv, float(duration + 15))
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                raise PrivateVisualCorpusError(
                    "private_overlay_capture_precondition_failed"
                ) from exc
            facts = _validate_captured_media(
                temporary,
                initial,
                duration=duration,
                probe=selected_probe,
            )
            after = postflight()
            _validate_postflight(preflight, after)
            try:
                _publish_no_replace(temporary, final)
            except Exception:
                _unlink_published_identity(final, initial)
                raise
            published = True
            new_mapping = dict(mapping)
            new_mapping[private_asset_id] = basename
            try:
                _write_index(overlay, new_mapping, previous=mapping)
            except Exception:
                _unlink_owned(final)
                published = False
                raise
            return CaptureResult(
                private_asset_id=private_asset_id,
                bytes=facts.bytes,
                sha256=facts.sha256,
                duration_ms=facts.duration_ms,
                codec=facts.codec,
                width=facts.width,
                height=facts.height,
                fps=float(facts.fps),
                video_streams=facts.video_streams,
                audio_streams=facts.audio_streams,
                subtitle_streams=facts.subtitle_streams,
                data_streams=facts.data_streams,
            )
        finally:
            if not published:
                _unlink_if_identity(temporary, initial)


def prepare_review_material(
    repository: Path,
    private_asset_id: str,
    *,
    runner: CaptureRunner | None = None,
    probe: CaptureProbe | None = None,
) -> ReviewPreparation:
    if _PRIVATE_ID.fullmatch(private_asset_id) is None:
        raise PrivateVisualCorpusError("private_overlay_review_incomplete")
    selected_runner = runner or _run_ffmpeg
    selected_probe = probe or probe_private_media
    overlay = _require_existing_overlay(Path(repository))
    with _capture_lock(overlay / "temp" / "capture.lock"):
        mapping = _load_index(overlay)
        basename = mapping.get(private_asset_id)
        if basename is None:
            raise PrivateVisualCorpusError("private_overlay_review_incomplete")
        _require_asset_inventory(overlay / "assets", mapping)
        media = overlay / "assets" / basename
        media_descriptor, media_identity = _open_private_descriptor(media)
        try:
            digest_before, bytes_before = _hash_private_descriptor(media_descriptor)
            held_media = Path(f"/dev/fd/{media_descriptor}")
            try:
                os.lseek(media_descriptor, 0, os.SEEK_SET)
                facts = selected_probe(held_media)
            except PrivateVisualCorpusError:
                raise
            except Exception as exc:
                raise PrivateVisualCorpusError("private_overlay_media_invalid") from exc
            digest_after, bytes_after = _hash_private_descriptor(media_descriptor)
            if (
                digest_before != digest_after
                or bytes_before != bytes_after
                or facts.sha256 != digest_after
                or facts.bytes != bytes_after
                or facts.audio_streams != 0
            ):
                raise PrivateVisualCorpusError("private_overlay_identity_mismatch")

            review_root = overlay / "review-frames"
            final = review_root / private_asset_id
            if final.exists():
                raise PrivateVisualCorpusError("private_overlay_review_incomplete")
            try:
                final.mkdir(mode=0o700)
            except OSError as exc:
                raise PrivateVisualCorpusError(
                    "private_overlay_review_incomplete"
                ) from exc
            expected_samples = max(1, round(facts.duration_ms / 500))
            commands = _review_ffmpeg_argv(held_media, final, expected_samples)
            try:
                for argv in commands:
                    try:
                        os.lseek(media_descriptor, 0, os.SEEK_SET)
                        if runner is None:
                            _run_ffmpeg(
                                argv,
                                30.0,
                                pass_fds=(media_descriptor,),
                            )
                        else:
                            runner(argv, 30.0)
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        raise PrivateVisualCorpusError(
                            "private_overlay_review_incomplete"
                        ) from exc
                settled_digest, settled_bytes = _hash_private_descriptor(
                    media_descriptor
                )
                held_after = os.fstat(media_descriptor)
                try:
                    media_after = os.stat(media, follow_symlinks=False)
                except OSError as exc:
                    raise PrivateVisualCorpusError(
                        "private_overlay_identity_mismatch"
                    ) from exc
                if (
                    settled_digest != digest_after
                    or settled_bytes != bytes_after
                    or not _same_stable_file(media_identity, held_after)
                    or not _same_private_file(media_identity, media_after)
                ):
                    raise PrivateVisualCorpusError(
                        "private_overlay_identity_mismatch"
                    )
                samples = sorted(final.glob("sample-*.png"))
                first = final / "first.png"
                last = final / "last.png"
                expected_names = {
                    *(
                        f"sample-{sequence:06d}.png"
                        for sequence in range(1, expected_samples + 1)
                    ),
                    "first.png",
                    "last.png",
                }
                actual_names = {entry.name for entry in os.scandir(final)}
                if (
                    len(samples) != expected_samples
                    or actual_names != expected_names
                    or not first.exists()
                    or not last.exists()
                ):
                    raise PrivateVisualCorpusError(
                        "private_overlay_review_incomplete"
                    )
                for frame in (*samples, first, last):
                    _seal_review_file(frame)
                manifest = final / "review-manifest.json"
                _write_private_json(
                    manifest,
                    {
                        "schema_version": 1,
                        "private_asset_id": private_asset_id,
                        "sha256": digest_after,
                        "sample_interval_ms": 500,
                        "sample_frame_count": len(samples),
                        "first_frame_present": True,
                        "last_frame_present": True,
                    },
                )
                _fsync_directory(final)
                _fsync_directory(review_root)
                return ReviewPreparation(
                    private_asset_id=private_asset_id,
                    sha256=digest_after,
                    sample_interval_ms=500,
                    sample_frame_count=len(samples),
                    first_frame_present=True,
                    last_frame_present=True,
                )
            except BaseException:
                _remove_owned_review_directory(final)
                raise
        finally:
            os.close(media_descriptor)


def review_status(repository: Path, private_asset_id: str) -> ReviewStatus:
    descriptor_path = Path(repository) / _DESCRIPTOR_RELATIVE
    overlay = Path(repository) / _PRIVATE_RELATIVE
    try:
        descriptor = load_private_overlay_descriptor(descriptor_path)
    except PrivateVisualOverlayError as exc:
        raise PrivateVisualCorpusError("private_overlay_review_incomplete") from exc
    selected = next(
        (
            asset
            for asset in descriptor.assets
            if asset.private_asset_id == private_asset_id
        ),
        None,
    )
    if selected is None or not overlay.exists():
        raise PrivateVisualCorpusError("private_overlay_review_incomplete")
    validation = validate_private_overlay(
        descriptor,
        overlay,
        probe=probe_private_media,
    )
    return ReviewStatus(
        private_asset_id=private_asset_id,
        state=(
            "complete"
            if validation.readiness is not LocalOverlayReadiness.LOCAL_UNAVAILABLE
            and review_complete_for_asset(selected, overlay)
            else "incomplete"
        ),
    )


def probe_private_media(path: Path) -> PrivateMediaFacts:
    candidate = Path(path)
    digest, byte_count = _hash_private_file(candidate)
    pass_fds: tuple[int, ...] = ()
    if candidate.parent == Path("/dev/fd") and candidate.name.isdigit():
        pass_fds = (int(candidate.name),)
    argv = (
        FFPROBE_EXECUTABLE,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(candidate),
    )
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
            pass_fds=pass_fds,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PrivateVisualCorpusError("private_overlay_media_invalid") from None
    if completed.returncode != 0 or len(completed.stdout) > _MAX_PROBE_BYTES:
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    try:
        payload = json.loads(completed.stdout)
        streams = payload["streams"]
        duration_ms = round(float(payload["format"]["duration"]) * 1000)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise PrivateVisualCorpusError("private_overlay_media_invalid") from None
    if not isinstance(streams, list):
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    video = [item for item in streams if _stream_type(item) == "video"]
    audio = [item for item in streams if _stream_type(item) == "audio"]
    subtitles = [item for item in streams if _stream_type(item) == "subtitle"]
    data = [
        item
        for item in streams
        if _stream_type(item) not in {"video", "audio", "subtitle"}
    ]
    if len(video) != 1:
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    selected = video[0]
    try:
        codec = selected["codec_name"]
        width = selected["width"]
        height = selected["height"]
        fps = _parse_fps(selected["avg_frame_rate"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        raise PrivateVisualCorpusError("private_overlay_media_invalid") from None
    return PrivateMediaFacts(
        bytes=byte_count,
        sha256=digest,
        video_streams=len(video),
        audio_streams=len(audio),
        subtitle_streams=len(subtitles),
        data_streams=len(data),
        duration_ms=duration_ms,
        codec=codec,
        width=width,
        height=height,
        fps=fps,
    )


def _validate_command(repository: Path) -> int:
    descriptor_path = repository / _DESCRIPTOR_RELATIVE
    overlay = repository / _PRIVATE_RELATIVE
    public = load_manifest(repository / _PUBLIC_MANIFEST_RELATIVE)
    if not descriptor_path.is_file() or not overlay.exists():
        result = PrivateOverlayValidation(
            readiness=LocalOverlayReadiness.LOCAL_UNAVAILABLE,
            reason="private_overlay_unavailable",
            asset_count=0,
            scenario_count=0,
        )
    else:
        try:
            descriptor = load_private_overlay_descriptor(descriptor_path)
            result = validate_private_overlay(
                descriptor,
                overlay,
                probe=probe_private_media,
            )
        except (OSError, PrivateVisualOverlayError):
            result = PrivateOverlayValidation(
                readiness=LocalOverlayReadiness.LOCAL_UNAVAILABLE,
                reason="private_overlay_unavailable",
                asset_count=0,
                scenario_count=0,
            )
    status = local_overlay_status(
        public.readiness,
        result,
        _REQUIRED_LOCAL_SCENARIOS,
    )
    _emit(
        result=(
            "PASS"
            if result.readiness is not LocalOverlayReadiness.LOCAL_UNAVAILABLE
            else "FAIL"
        ),
        operation="validate",
        public_readiness=status.public_readiness.value,
        local_readiness=status.local_readiness.value,
        reason=status.reason,
        asset_count=result.asset_count,
        scenario_count=result.scenario_count,
    )
    return 0 if result.readiness is not LocalOverlayReadiness.LOCAL_UNAVAILABLE else 2


def _validate_preflight(value: CapturePreflight) -> None:
    bounded_ints = (
        value.pending_command_responses,
        value.residual_sender_count,
        value.producer_count,
        value.producer_generation,
        value.consumer_count,
    )
    if (
        not isinstance(value, CapturePreflight)
        or value.camera_reply_enabled is not False
        or value.speaker_state != "closed"
        or value.pending_command_responses != 0
        or value.residual_sender_count != 0
        or value.configured_transport != "auto"
        or value.producer_count != 1
        or value.negotiated_protocol not in {"cs2+udp", "cs2+tcp"}
        or value.video_media_ready is not True
        or value.video_bytes_increased is not True
        or value.producer_replaced is not False
        or any(type(item) is not int or item < 0 for item in bounded_ints)
    ):
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")


def _validate_postflight(before: CapturePreflight, after: CapturePreflight) -> None:
    _validate_preflight(after)
    if (
        after.negotiated_protocol != before.negotiated_protocol
        or after.producer_generation != before.producer_generation
        or after.consumer_count != before.consumer_count
    ):
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")


def _collect_capture_preflight(repository: Path) -> CapturePreflight:
    try:
        settings = AppSettings.load(repository / "runtime/settings.yaml")
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        media = collect_snapshot(repository, opener=opener)
        evidence = parse_source_media(_read_source(opener))
    except (
        OSError,
        ValueError,
        HTTPError,
        URLError,
        TimeoutError,
        XiaomiMediaDiagnosticError,
    ):
        raise PrivateVisualCorpusError(
            "private_overlay_capture_precondition_failed"
        ) from None
    return CapturePreflight(
        camera_reply_enabled=settings.voice_care.camera_reply_enabled,
        speaker_state=evidence.speaker_state,
        pending_command_responses=evidence.pending_command_responses,
        residual_sender_count=evidence.residual_sender_count,
        configured_transport=media.configured_transport,
        producer_count=media.producer_count,
        negotiated_protocol=media.negotiated_protocol,
        producer_generation=media.producer_generation,
        consumer_count=media.consumer_count,
        video_media_ready=media.video_media_ready,
        video_bytes_increased=media.video_bytes_increased,
        producer_replaced=media.producer_replaced,
    )


def _read_source(opener) -> bytes:
    request = Request(
        _SOURCE_STATUS_URL,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=_SOURCE_TIMEOUT_SECONDS) as response:
            if getattr(response, "status", None) != 200:
                raise PrivateVisualCorpusError(
                    "private_overlay_capture_precondition_failed"
                )
            payload = response.read(_MAX_PROBE_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise PrivateVisualCorpusError(
            "private_overlay_capture_precondition_failed"
        ) from None
    if not 0 < len(payload) <= _MAX_PROBE_BYTES:
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")
    return payload


def _prepare_overlay_layout(repository: Path) -> Path:
    root = repository.absolute()
    _require_directory(root, private=False)
    runtime = root / "runtime"
    test_corpus = runtime / "test-corpus"
    visual = test_corpus / "visual"
    overlay = visual / "private-overlay"
    for path, private in (
        (runtime, False),
        (test_corpus, True),
        (visual, True),
        (overlay, True),
        (overlay / "assets", True),
        (overlay / "review-frames", True),
        (overlay / "results", True),
        (overlay / "temp", True),
    ):
        _ensure_directory(path, private=private)
    _require_root_inventory(overlay)
    return overlay


def _require_existing_overlay(repository: Path) -> Path:
    root = repository.absolute()
    overlay = root / _PRIVATE_RELATIVE
    try:
        _require_directory(root, private=False)
        _require_directory(overlay, private=True)
        for name in ("assets", "review-frames", "results", "temp"):
            _require_directory(overlay / name, private=True)
        _require_root_inventory(overlay)
    except PrivateVisualCorpusError as exc:
        raise PrivateVisualCorpusError("private_overlay_review_incomplete") from exc
    return overlay


def _ensure_directory(path: Path, *, private: bool) -> None:
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid") from exc
    _require_directory(path, private=private)


def _require_directory(path: Path, *, private: bool) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid") from exc
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or (private and stat.S_IMODE(value.st_mode) != 0o700)
    ):
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid")


def _require_root_inventory(overlay: Path) -> None:
    allowed = {"assets", "review-frames", "results", "temp", "index.json"}
    actual = {entry.name for entry in os.scandir(overlay)}
    if not {"assets", "review-frames", "results", "temp"}.issubset(actual):
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid")
    if not actual.issubset(allowed):
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid")


@contextmanager
def _capture_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise PrivateVisualCorpusError(
            "private_overlay_capture_precondition_failed"
        ) from exc
    try:
        info = os.fstat(descriptor)
        entry = os.stat(path, follow_symlinks=False)
        if not _same_private_file(info, entry):
            raise PrivateVisualCorpusError(
                "private_overlay_capture_precondition_failed"
            )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise PrivateVisualCorpusError(
                "private_overlay_capture_precondition_failed"
            ) from exc
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)


def _load_index(overlay: Path) -> dict[str, str]:
    path = overlay / "index.json"
    if not path.exists():
        return {}
    raw = _read_private_file(path, _MAX_INDEX_BYTES)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "assets"}
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("assets"), list)
        or not 1 <= len(payload["assets"]) <= 20
    ):
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid")
    mapping: dict[str, str] = {}
    basenames: set[str] = set()
    for item in payload["assets"]:
        if not isinstance(item, dict) or set(item) != {
            "private_asset_id",
            "basename",
        }:
            raise PrivateVisualCorpusError("private_overlay_mapping_invalid")
        asset_id = item["private_asset_id"]
        basename = item["basename"]
        if (
            type(asset_id) is not str
            or _PRIVATE_ID.fullmatch(asset_id) is None
            or basename != f"{asset_id}.mkv"
            or asset_id in mapping
            or basename in basenames
        ):
            raise PrivateVisualCorpusError("private_overlay_mapping_invalid")
        mapping[asset_id] = basename
        basenames.add(basename)
    return mapping


def _read_private_file(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid") from exc
    try:
        before = os.fstat(descriptor)
        if not _private_file(before):
            raise PrivateVisualCorpusError("private_overlay_permissions_invalid")
        raw = os.read(descriptor, maximum + 1)
        after = os.fstat(descriptor)
        entry = os.stat(path, follow_symlinks=False)
        if (
            len(raw) > maximum
            or not _same_private_file(before, after)
            or not _same_private_file(after, entry)
        ):
            raise PrivateVisualCorpusError("private_overlay_mapping_invalid")
        return raw
    finally:
        os.close(descriptor)


def _require_asset_inventory(path: Path, mapping: Mapping[str, str]) -> None:
    actual = {entry.name for entry in os.scandir(path)}
    if actual != set(mapping.values()):
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid")


def _ffmpeg_argv(duration: int, destination: Path) -> tuple[str, ...]:
    return (
        FFMPEG_EXECUTABLE,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        _SOURCE_ALIAS,
        "-t",
        str(duration),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-c:v",
        "copy",
        "-f",
        "matroska",
        str(destination),
    )


def _review_ffmpeg_argv(
    source: Path,
    destination: Path,
    expected_samples: int,
) -> tuple[tuple[str, ...], ...]:
    prefix = (
        FFMPEG_EXECUTABLE,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
    )
    return (
        prefix
        + (
            "-i",
            str(source),
            "-vf",
            "fps=2",
            "-vsync",
            "0",
            "-frames:v",
            str(expected_samples),
            str(destination / "sample-%06d.png"),
        ),
        prefix
        + (
            "-ss",
            "0",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(destination / "first.png"),
        ),
        prefix
        + (
            "-sseof",
            "-1",
            "-i",
            str(source),
            "-vf",
            "reverse",
            "-frames:v",
            "1",
            str(destination / "last.png"),
        ),
    )


def _run_ffmpeg(
    argv: tuple[str, ...],
    timeout_seconds: float,
    *,
    pass_fds: tuple[int, ...] = (),
) -> None:
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=_child_private_umask,
            pass_fds=pass_fds,
        )
    except OSError:
        raise PrivateVisualCorpusError(
            "private_overlay_capture_precondition_failed"
        ) from None
    try:
        returncode = process.wait(timeout=timeout_seconds)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        process.terminate()
        try:
            process.wait(timeout=_PROCESS_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_PROCESS_GRACE_SECONDS)
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise PrivateVisualCorpusError(
            "private_overlay_capture_precondition_failed"
        ) from None
    if returncode != 0:
        raise PrivateVisualCorpusError("private_overlay_capture_precondition_failed")


def _child_private_umask() -> None:
    os.umask(0o077)


def _seal_review_file(path: Path) -> None:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_MEDIA_BYTES
        ):
            raise PrivateVisualCorpusError("private_overlay_review_incomplete")
        path.chmod(0o600)
        after = path.lstat()
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_review_incomplete") from exc
    if not _same_identity(before, after) or not _private_file(after):
        raise PrivateVisualCorpusError("private_overlay_review_incomplete")


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                if written <= 0:
                    raise OSError("short private write")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_review_incomplete") from exc


def _remove_owned_review_directory(path: Path) -> None:
    try:
        directory = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if (
        not stat.S_ISDIR(directory.st_mode)
        or stat.S_ISLNK(directory.st_mode)
        or directory.st_uid != os.getuid()
        or stat.S_IMODE(directory.st_mode) != 0o700
    ):
        return
    try:
        entries = list(os.scandir(path))
    except OSError:
        return
    for entry in entries:
        try:
            value = entry.stat(follow_symlinks=False)
        except OSError:
            return
        if (
            not stat.S_ISREG(value.st_mode)
            or stat.S_ISLNK(value.st_mode)
            or value.st_uid != os.getuid()
            or value.st_nlink != 1
        ):
            return
    try:
        for entry in entries:
            os.unlink(entry.path)
        os.rmdir(path)
    except OSError:
        return


def _validate_captured_media(
    path: Path,
    initial: os.stat_result,
    *,
    duration: int,
    probe: CaptureProbe,
) -> PrivateMediaFacts:
    try:
        before = path.lstat()
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_media_invalid") from exc
    if not _same_private_file(initial, before):
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch")
    try:
        facts = probe(path)
    except PrivateVisualCorpusError:
        raise
    except Exception as exc:
        raise PrivateVisualCorpusError("private_overlay_media_invalid") from exc
    try:
        after = path.lstat()
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch") from exc
    if not _same_stable_file(before, after):
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch")
    if not isinstance(facts, PrivateMediaFacts):
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    if facts.audio_streams != 0:
        raise PrivateVisualCorpusError("private_overlay_audio_present")
    if (
        facts.video_streams != 1
        or facts.subtitle_streams != 0
        or facts.data_streams != 0
        or not 1 <= facts.bytes <= _MAX_MEDIA_BYTES
        or facts.bytes != after.st_size
        or facts.codec not in {"hevc", "h264", "mjpeg"}
        or type(facts.width) is not int
        or not 1 <= facts.width <= 4096
        or type(facts.height) is not int
        or not 1 <= facts.height <= 2160
        or type(facts.fps) not in {int, float}
        or not math.isfinite(float(facts.fps))
        or not 0 < float(facts.fps) <= 120
        or type(facts.duration_ms) is not int
        or abs(facts.duration_ms - duration * 1000) > 1000
    ):
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    digest, byte_count = _hash_private_file(path)
    if facts.sha256 != digest or facts.bytes != byte_count:
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch")
    return facts


def _hash_private_file(path: Path) -> tuple[str, int]:
    descriptor, _identity = _open_private_descriptor(path)
    try:
        return _hash_private_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _open_private_descriptor(path: Path) -> tuple[int, os.stat_result]:
    if path.parent == Path("/dev/fd") and path.name.isdigit():
        try:
            descriptor = os.dup(int(path.name))
            held = os.fstat(descriptor)
        except OSError as exc:
            raise PrivateVisualCorpusError(
                "private_overlay_identity_mismatch"
            ) from exc
        if not _private_file(held) or held.st_size > _MAX_MEDIA_BYTES:
            os.close(descriptor)
            raise PrivateVisualCorpusError(
                "private_overlay_permissions_invalid"
            )
        return descriptor, held
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        entry = path.lstat()
        descriptor = os.open(path, flags)
        held = os.fstat(descriptor)
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch") from exc
    if (
        not _same_private_file(entry, held)
        or held.st_size > _MAX_MEDIA_BYTES
    ):
        os.close(descriptor)
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid")
    return descriptor, held


def _hash_private_descriptor(descriptor: int) -> tuple[str, int]:
    before = os.fstat(descriptor)
    if not _private_file(before) or before.st_size > _MAX_MEDIA_BYTES:
        raise PrivateVisualCorpusError("private_overlay_permissions_invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(
            descriptor,
            min(1024 * 1024, _MAX_MEDIA_BYTES - total + 1),
        )
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_MEDIA_BYTES:
            raise PrivateVisualCorpusError("private_overlay_media_invalid")
        digest.update(chunk)
    after = os.fstat(descriptor)
    if not _same_stable_file(before, after) or total != after.st_size:
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch")
    return digest.hexdigest(), total


def _publish_no_replace(temporary: Path, final: Path) -> None:
    try:
        os.link(temporary, final, follow_symlinks=False)
        os.unlink(temporary)
        _fsync_directory(temporary.parent)
        _fsync_directory(final.parent)
    except FileExistsError as exc:
        raise PrivateVisualCorpusError("private_overlay_duplicate_clip") from exc
    except OSError as exc:
        raise PrivateVisualCorpusError("private_overlay_identity_mismatch") from exc


def _index_bytes(mapping: Mapping[str, str]) -> bytes:
    payload = {
        "schema_version": 1,
        "assets": [
            {"private_asset_id": asset_id, "basename": mapping[asset_id]}
            for asset_id in sorted(mapping)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")


def _write_index(
    overlay: Path,
    mapping: Mapping[str, str],
    *,
    previous: Mapping[str, str],
) -> None:
    raw = _index_bytes(mapping)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".index-",
        suffix=".tmp",
        dir=overlay / "temp",
    )
    temporary = Path(raw_path)
    rollback: Path | None = None
    installed = False
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, raw)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if previous:
            rollback_descriptor, rollback_path = tempfile.mkstemp(
                prefix=".index-rollback-",
                suffix=".tmp",
                dir=overlay / "temp",
            )
            rollback = Path(rollback_path)
            try:
                os.fchmod(rollback_descriptor, 0o600)
                os.write(rollback_descriptor, _index_bytes(previous))
                os.fsync(rollback_descriptor)
            finally:
                os.close(rollback_descriptor)
        os.replace(temporary, overlay / "index.json")
        installed = True
        _fsync_directory(temporary.parent)
        _fsync_directory(overlay)
    except OSError as exc:
        if installed:
            try:
                if rollback is None:
                    _unlink_owned(overlay / "index.json")
                else:
                    os.replace(rollback, overlay / "index.json")
                    rollback = None
                _fsync_directory(overlay)
            except OSError:
                pass
        raise PrivateVisualCorpusError("private_overlay_mapping_invalid") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            _unlink_owned(temporary)
        if rollback is not None and rollback.exists():
            _unlink_owned(rollback)


def _unlink_if_identity(path: Path, expected: os.stat_result) -> None:
    try:
        actual = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if _same_identity(actual, expected) and _private_file(actual):
        try:
            path.unlink()
        except OSError:
            pass


def _unlink_published_identity(path: Path, expected: os.stat_result) -> None:
    try:
        actual = path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        return
    if (
        _same_identity(actual, expected)
        and stat.S_ISREG(actual.st_mode)
        and not stat.S_ISLNK(actual.st_mode)
        and actual.st_uid == os.getuid()
        and stat.S_IMODE(actual.st_mode) == 0o600
        and actual.st_nlink in {1, 2}
    ):
        try:
            path.unlink()
        except OSError:
            pass


def _unlink_owned(path: Path) -> None:
    try:
        actual = path.lstat()
    except FileNotFoundError:
        return
    if _private_file(actual):
        path.unlink()


def _private_file(value: os.stat_result) -> bool:
    return bool(
        stat.S_ISREG(value.st_mode)
        and not stat.S_ISLNK(value.st_mode)
        and value.st_uid == os.getuid()
        and stat.S_IMODE(value.st_mode) == 0o600
        and value.st_nlink == 1
    )


def _same_private_file(left: os.stat_result, right: os.stat_result) -> bool:
    return _private_file(left) and _private_file(right) and _same_identity(left, right)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_stable_file(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        _same_private_file(left, right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stream_type(value: object) -> str:
    if not isinstance(value, dict) or type(value.get("codec_type")) is not str:
        raise PrivateVisualCorpusError("private_overlay_media_invalid")
    return value["codec_type"]


def _parse_fps(value: object) -> float:
    if type(value) is not str or "/" not in value:
        raise ValueError
    numerator, denominator = value.split("/", 1)
    fps = float(numerator) / float(denominator)
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError
    return fps


def _parse_asset_id(value: str) -> str:
    if _PRIVATE_ID.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("invalid private asset id")
    return value


def _asset_id() -> str:
    return f"plc-{secrets.token_hex(16)}"


def _emit_capture(result: CaptureResult) -> None:
    _emit(
        result="PASS",
        operation="capture",
        private_asset_id=result.private_asset_id,
        bytes=result.bytes,
        sha256=result.sha256,
        duration_ms=result.duration_ms,
        codec=result.codec,
        width=result.width,
        height=result.height,
        fps=result.fps,
        video_streams=result.video_streams,
        audio_streams=result.audio_streams,
        subtitle_streams=result.subtitle_streams,
        data_streams=result.data_streams,
    )


def _emit(**fields: object) -> None:
    for key, value in fields.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    raise SystemExit(main())
