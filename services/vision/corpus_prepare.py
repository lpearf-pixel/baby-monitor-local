from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Protocol

from packages.contracts.visual_corpus import (
    NormalizationProfile,
    OcclusionExtent,
    PreparationRecipe,
    RecipeKind,
    VisualCorpusClip,
)
from services.vision.corpus_storage import (
    CorpusLayout,
    CorpusStorageError,
    sha256_file,
)


PROBE_TIMEOUT_SECONDS = 10.0
PREPARE_TIMEOUT_SECONDS = 90.0
MAX_PROBE_BYTES = 64 * 1024
MAX_PREPARED_BYTES = 256 * 1024 * 1024


class CorpusPrepareError(RuntimeError):
    """A stable, redacted preparation failure."""


@dataclass(frozen=True)
class MediaProbe:
    codec: str
    width: int
    height: int
    fps: float
    duration_ms: int
    video_stream_count: int
    other_stream_count: int


@dataclass(frozen=True)
class PreparedArtifact:
    profile_id: str
    path: Path
    sha256: str
    byte_count: int
    recipe_digest: str
    ffmpeg_version_digest: str
    reused: bool


@dataclass(frozen=True)
class PreparedClip:
    clip_id: str
    artifacts: tuple[PreparedArtifact, ...]


class PrepareRunner(Protocol):
    def run_json(self, argv: tuple[str, ...], *, timeout_seconds: float) -> bytes: ...

    def run_to_fd(
        self,
        argv: tuple[str, ...],
        *,
        output_fd: int,
        timeout_seconds: float,
    ) -> None: ...

    def supports_encoder(self, name: str) -> bool: ...

    def version_digest(self) -> str: ...


class FfmpegCommandRunner:
    def __init__(self) -> None:
        self._encoders: frozenset[str] | None = None
        self._version_digest: str | None = None

    def run_json(self, argv: tuple[str, ...], *, timeout_seconds: float) -> bytes:
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CorpusPrepareError("visual_corpus_probe_failed") from exc
        if completed.returncode != 0 or len(completed.stdout) > MAX_PROBE_BYTES:
            raise CorpusPrepareError("visual_corpus_probe_failed")
        return completed.stdout

    def run_to_fd(
        self,
        argv: tuple[str, ...],
        *,
        output_fd: int,
        timeout_seconds: float,
    ) -> None:
        try:
            child = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output_fd,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise CorpusPrepareError("visual_corpus_prepare_failed") from exc
        try:
            returncode = child.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(child)
            raise CorpusPrepareError("visual_corpus_prepare_timeout") from exc
        except KeyboardInterrupt as exc:
            _terminate_process_group(child)
            raise CorpusPrepareError("visual_corpus_prepare_interrupted") from exc
        if returncode != 0:
            raise CorpusPrepareError("visual_corpus_prepare_failed")

    def supports_encoder(self, name: str) -> bool:
        if self._encoders is None:
            payload = self.run_json(
                ("ffmpeg", "-hide_banner", "-encoders"),
                timeout_seconds=PROBE_TIMEOUT_SECONDS,
            )
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CorpusPrepareError("visual_corpus_encoder_probe_failed") from exc
            self._encoders = frozenset(
                fields[1]
                for line in text.splitlines()
                if len(fields := line.split()) >= 2 and fields[0].startswith("V")
            )
        return name in self._encoders

    def version_digest(self) -> str:
        if self._version_digest is None:
            payload = self.run_json(
                ("ffmpeg", "-version"),
                timeout_seconds=PROBE_TIMEOUT_SECONDS,
            )
            self._version_digest = hashlib.sha256(payload).hexdigest()
        return self._version_digest


def probe_media(
    path: Path,
    *,
    runner: PrepareRunner,
    require_video_only: bool,
) -> MediaProbe:
    argv = (
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    )
    try:
        payload = runner.run_json(argv, timeout_seconds=PROBE_TIMEOUT_SECONDS)
        if len(payload) > MAX_PROBE_BYTES:
            raise ValueError
        document = json.loads(payload.decode("utf-8"))
        streams = document["streams"]
        video_streams = [item for item in streams if item.get("codec_type") == "video"]
        other_streams = [item for item in streams if item.get("codec_type") != "video"]
        if len(video_streams) != 1 or (require_video_only and other_streams):
            raise ValueError
        video = video_streams[0]
        duration = float(document["format"]["duration"])
        fps_fraction = Fraction(video["avg_frame_rate"])
        fps = float(fps_fraction)
        width = int(video["width"])
        height = int(video["height"])
        codec = str(video["codec_name"])
        if (
            not math.isfinite(duration)
            or duration <= 0
            or not math.isfinite(fps)
            or fps <= 0
            or not 1 <= width <= 4096
            or not 1 <= height <= 2160
            or codec not in {"hevc", "h264", "mjpeg", "vp8", "vp9", "theora"}
        ):
            raise ValueError
        return MediaProbe(
            codec=codec,
            width=width,
            height=height,
            fps=fps,
            duration_ms=round(duration * 1000),
            video_stream_count=1,
            other_stream_count=len(other_streams),
        )
    except CorpusPrepareError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise CorpusPrepareError("visual_corpus_media_invalid") from exc


class CorpusPreparer:
    def __init__(
        self,
        *,
        layout: CorpusLayout,
        profiles: tuple[NormalizationProfile, ...],
        source_resolver: Callable[[str], Path],
        runner: PrepareRunner | None = None,
    ) -> None:
        self._layout = layout
        self._profiles = profiles
        self._source_resolver = source_resolver
        self._runner = runner or FfmpegCommandRunner()

    def prepare_clip(self, clip: VisualCorpusClip) -> PreparedClip:
        try:
            source = self._source_resolver(clip.source_id)
            source_digest, _source_bytes = sha256_file(
                source,
                max_bytes=128 * 1024 * 1024,
            )
        except (CorpusStorageError, OSError) as exc:
            raise CorpusPrepareError("visual_corpus_source_invalid") from exc
        version_digest = self._runner.version_digest()
        artifacts = tuple(
            self._prepare_profile(
                clip,
                profile,
                source=source,
                source_digest=source_digest,
                version_digest=version_digest,
            )
            for profile in self._profiles
        )
        return PreparedClip(clip_id=clip.clip_id, artifacts=artifacts)

    def _prepare_profile(
        self,
        clip: VisualCorpusClip,
        profile: NormalizationProfile,
        *,
        source: Path,
        source_digest: str,
        version_digest: str,
    ) -> PreparedArtifact:
        encoder = _encoder_for(profile)
        if not self._runner.supports_encoder(encoder):
            reason = (
                "visual_corpus_hevc_encoder_unavailable"
                if encoder == "libx265"
                else "visual_corpus_encoder_unavailable"
            )
            raise CorpusPrepareError(reason)
        identity = _recipe_digest(
            clip,
            profile,
            source_digest=source_digest,
            version_digest=version_digest,
        )
        final = self._layout.prepared / (
            f"{clip.clip_id.lower()}.{profile.profile_id}.{identity[:16]}.mkv"
        )
        if final.exists():
            return self._validate_artifact(
                final,
                profile,
                expected_duration_ms=clip.end_ms - clip.start_ms,
                recipe_digest=identity,
                version_digest=version_digest,
                reused=True,
            )

        temporary = self._layout.new_temporary_file(prefix="prepare")
        try:
            argv = _build_ffmpeg_argv(clip, profile, source=source)
            self._runner.run_to_fd(
                argv,
                output_fd=temporary.descriptor,
                timeout_seconds=PREPARE_TIMEOUT_SECONDS,
            )
            os.fsync(temporary.descriptor)
            artifact = self._validate_artifact(
                temporary.path,
                profile,
                expected_duration_ms=clip.end_ms - clip.start_ms,
                recipe_digest=identity,
                version_digest=version_digest,
                reused=False,
            )
            self._layout.publish_no_replace(temporary, final)
            return PreparedArtifact(
                profile_id=artifact.profile_id,
                path=final,
                sha256=artifact.sha256,
                byte_count=artifact.byte_count,
                recipe_digest=artifact.recipe_digest,
                ffmpeg_version_digest=artifact.ffmpeg_version_digest,
                reused=False,
            )
        except CorpusPrepareError:
            raise
        except CorpusStorageError as exc:
            raise CorpusPrepareError("visual_corpus_publish_failed") from exc
        finally:
            temporary.close()

    def _validate_artifact(
        self,
        path: Path,
        profile: NormalizationProfile,
        *,
        expected_duration_ms: int,
        recipe_digest: str,
        version_digest: str,
        reused: bool,
    ) -> PreparedArtifact:
        probe = probe_media(path, runner=self._runner, require_video_only=True)
        codec_matches = probe.codec == profile.codec
        if (
            not codec_matches
            or probe.width != profile.width
            or probe.height != profile.height
            or abs(probe.fps - profile.fps) > 0.01
            or abs(probe.duration_ms - expected_duration_ms) > max(200, round(1000 / profile.fps))
        ):
            raise CorpusPrepareError("visual_corpus_profile_mismatch")
        try:
            digest, byte_count = sha256_file(path, max_bytes=MAX_PREPARED_BYTES)
        except CorpusStorageError as exc:
            raise CorpusPrepareError("visual_corpus_artifact_invalid") from exc
        return PreparedArtifact(
            profile_id=profile.profile_id,
            path=path,
            sha256=digest,
            byte_count=byte_count,
            recipe_digest=recipe_digest,
            ffmpeg_version_digest=version_digest,
            reused=reused,
        )


def _recipe_digest(
    clip: VisualCorpusClip,
    profile: NormalizationProfile,
    *,
    source_digest: str,
    version_digest: str,
) -> str:
    payload = {
        "clip": clip.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "source_digest": source_digest,
        "ffmpeg_version_digest": version_digest,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _build_ffmpeg_argv(
    clip: VisualCorpusClip,
    profile: NormalizationProfile,
    *,
    source: Path,
) -> tuple[str, ...]:
    duration_seconds = (clip.end_ms - clip.start_ms) / 1000
    input_args: tuple[str, ...] = ()
    if clip.recipe.kind is RecipeKind.LOOP_TO_MINIMUM:
        input_args = ("-stream_loop", "-1")
    filters = _filters_for(clip.recipe, profile)
    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *input_args,
        "-ss",
        f"{clip.start_ms / 1000:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0",
        "-an",
        "-map_metadata",
        "-1",
        "-vf",
        ",".join(filters),
        "-fps_mode",
        "cfr",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        _encoder_for(profile),
        "-f",
        "matroska",
        "pipe:1",
    )


def _filters_for(
    recipe: PreparationRecipe,
    profile: NormalizationProfile,
) -> tuple[str, ...]:
    recipe_filters: dict[RecipeKind, tuple[str, ...]] = {
        RecipeKind.SOURCE_SEGMENT: (),
        RecipeKind.SIMULATED_IR: ("format=gray", "eq=contrast=1.2:brightness=-0.05"),
        RecipeKind.LOW_CONTRAST: ("eq=contrast=0.5:brightness=-0.05",),
        RecipeKind.SYNTHETIC_SCALE: (
            "scale=iw*0.35:ih*0.35",
            "pad=iw/0.35:ih/0.35:(ow-iw)/2:(oh-ih)/2:black",
        ),
        RecipeKind.LOOP_TO_MINIMUM: (),
    }
    if recipe.kind is RecipeKind.BOUNDED_OCCLUSION:
        if recipe.occlusion_extent is OcclusionExtent.MAJORITY:
            selected = (
                "drawbox=x=iw*0.18:y=ih*0.10:w=iw*0.64:h=ih*0.72:color=black@0.85:t=fill",
            )
        else:
            selected = (
                "drawbox=x=iw*0.35:y=ih*0.20:w=iw*0.30:h=ih*0.30:color=black@0.85:t=fill",
            )
    else:
        selected = recipe_filters[recipe.kind]
    normalize = (
        f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease",
        f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={profile.fps}",
        "setsar=1",
    )
    return (*selected, *normalize)


def _encoder_for(profile: NormalizationProfile) -> str:
    return {
        "hevc": "libx265",
        "h264": "libx264",
        "mjpeg": "mjpeg",
    }[profile.codec]


def _terminate_process_group(child: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return
