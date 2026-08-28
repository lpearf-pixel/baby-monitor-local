from __future__ import annotations

import hashlib
import importlib
import json
import os
import signal
from pathlib import Path

import pytest

from packages.contracts.visual_corpus import (
    NormalizationProfile,
    VisualCorpusClip,
)
from services.vision.corpus_storage import CorpusLayout


def prepare_module():
    return importlib.import_module("services.vision.corpus_prepare")


def clip(
    *,
    clip_id: str = "DAY-01",
    recipe: str = "SOURCE_SEGMENT",
    parent_clip_id: str | None = None,
    end_ms: int = 12_000,
) -> VisualCorpusClip:
    payload: dict[str, object] = {
        "clip_id": clip_id,
        "source_id": "public-source",
        "source_type": "PUBLIC_DATASET" if recipe == "SOURCE_SEGMENT" else "SYNTHETIC",
        "scenario_ids": ["DAY-01"],
        "start_ms": 2_000,
        "end_ms": end_ms,
        "recipe": {"kind": recipe},
        "labels": {
            "framing": "medium",
            "subject_scale": "medium",
            "subject_frame_area_ratio": 0.2,
            "camera_angle": "high_oblique",
            "environment": "crib",
            "lighting": "day",
            "baby_visibility": "full",
            "motion": "mild",
            "adult_visibility": "absent",
            "object_state": "mixed",
            "wide_content_role": "none",
        },
        "temporal_labels": [],
        "label_provenance": "frame_review",
        "label_confidence": 0.9,
        "review_state": "reviewed",
    }
    if parent_clip_id is not None:
        payload["parent_clip_id"] = parent_clip_id
    return VisualCorpusClip.model_validate(payload)


def profile(profile_id: str = "xiaomi_source_hd") -> NormalizationProfile:
    values = {
        "xiaomi_source_hd": (2560, 1440, 10, "hevc"),
        "xiaomi_live": (1280, 720, 10, "h264"),
        "analysis_realtime": (960, 540, 5, "mjpeg"),
        "analysis_slow": (960, 540, 1, "mjpeg"),
    }
    width, height, fps, codec = values[profile_id]
    return NormalizationProfile(
        profile_id=profile_id,
        width=width,
        height=height,
        fps=fps,
        codec=codec,
    )


def valid_probe(
    *,
    codec: str = "hevc",
    width: int = 2560,
    height: int = 1440,
    fps: str = "10/1",
    duration: str = "10.000000",
) -> bytes:
    return json.dumps(
        {
            "format": {"duration": duration},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": codec,
                    "width": width,
                    "height": height,
                    "avg_frame_rate": fps,
                }
            ],
        }
    ).encode("ascii")


class RecordingRunner:
    def __init__(self, probe: bytes | None = None) -> None:
        self.probe = probe or valid_probe()
        self.json_calls: list[tuple[tuple[str, ...], float]] = []
        self.output_calls: list[tuple[tuple[str, ...], int, float]] = []
        self.supported = {"libx265", "libx264", "mjpeg"}

    def run_json(self, argv: tuple[str, ...], *, timeout_seconds: float) -> bytes:
        self.json_calls.append((argv, timeout_seconds))
        return self.probe

    def run_to_fd(
        self,
        argv: tuple[str, ...],
        *,
        output_fd: int,
        timeout_seconds: float,
    ) -> None:
        self.output_calls.append((argv, output_fd, timeout_seconds))
        os.write(output_fd, b"prepared-video")

    def supports_encoder(self, name: str) -> bool:
        return name in self.supported

    def version_digest(self) -> str:
        return "2" * 64


def layout(tmp_path: Path) -> CorpusLayout:
    repo = tmp_path / "repo"
    repo.mkdir()
    return CorpusLayout.for_repository(repo)


def source_file(corpus_layout: CorpusLayout) -> Path:
    path = corpus_layout.downloads / "public-source.source"
    path.write_bytes(b"source-video")
    path.chmod(0o600)
    return path


def test_probe_media_uses_fixed_bounded_ffprobe_command(tmp_path: Path) -> None:
    module = prepare_module()
    runner = RecordingRunner()
    media = tmp_path / "prepared.mkv"
    media.write_bytes(b"fixture")

    result = module.probe_media(media, runner=runner, require_video_only=True)

    assert result.codec == "hevc"
    assert (result.width, result.height, result.fps, result.duration_ms) == (
        2560,
        1440,
        10.0,
        10_000,
    )
    argv, timeout = runner.json_calls[0]
    assert argv == (
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(media),
    )
    assert timeout == 10.0


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        json.dumps({"format": {"duration": "nan"}, "streams": []}).encode(),
        json.dumps(
            {
                "format": {"duration": "10"},
                "streams": [
                    {"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 1, "height": 1, "avg_frame_rate": "1/0"},
                    {"index": 1, "codec_type": "video", "codec_name": "hevc", "width": 1, "height": 1, "avg_frame_rate": "1/1"},
                ],
            }
        ).encode(),
    ],
)
def test_probe_media_rejects_malformed_or_multiple_video_streams(
    tmp_path: Path,
    payload: bytes,
) -> None:
    module = prepare_module()
    media = tmp_path / "prepared.mkv"
    media.write_bytes(b"fixture")

    with pytest.raises(
        module.CorpusPrepareError,
        match="^visual_corpus_media_invalid$",
    ):
        module.probe_media(
            media,
            runner=RecordingRunner(payload),
            require_video_only=True,
        )


def test_prepare_hevc_uses_fixed_profile_and_publishes_verified_artifact(
    tmp_path: Path,
) -> None:
    module = prepare_module()
    corpus_layout = layout(tmp_path)
    source = source_file(corpus_layout)
    runner = RecordingRunner()
    preparer = module.CorpusPreparer(
        layout=corpus_layout,
        profiles=(profile(),),
        source_resolver=lambda _source_id: source,
        runner=runner,
    )

    prepared = preparer.prepare_clip(clip())

    assert prepared.clip_id == "DAY-01"
    assert len(prepared.artifacts) == 1
    artifact = prepared.artifacts[0]
    assert artifact.profile_id == "xiaomi_source_hd"
    assert artifact.sha256 == hashlib.sha256(b"prepared-video").hexdigest()
    assert artifact.byte_count == len(b"prepared-video")
    assert artifact.ffmpeg_version_digest == "2" * 64
    assert artifact.path.read_bytes() == b"prepared-video"
    argv, _fd, timeout = runner.output_calls[0]
    assert argv[:3] == ("ffmpeg", "-nostdin", "-hide_banner")
    assert argv[-3:] == ("-f", "matroska", "pipe:1")
    assert "-an" in argv
    assert "libx265" in argv
    rendered_argv = " ".join(argv)
    assert "fps=10" in rendered_argv
    assert "scale=2560:1440:force_original_aspect_ratio=decrease" in rendered_argv
    assert timeout == 90.0


def test_ffmpeg_keyboard_interrupt_terminates_owned_process_group(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = prepare_module()
    waits = iter((KeyboardInterrupt(), 0))
    signals: list[tuple[int, int]] = []

    class Child:
        pid = 4321

        def wait(self, *, timeout: float):
            outcome = next(waits)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: Child())
    monkeypatch.setattr(
        module.os,
        "killpg",
        lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )
    destination = tmp_path / "output.mkv"
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        with pytest.raises(
            module.CorpusPrepareError,
            match="^visual_corpus_prepare_interrupted$",
        ):
            module.FfmpegCommandRunner().run_to_fd(
                ("ffmpeg",),
                output_fd=descriptor,
                timeout_seconds=90,
            )
    finally:
        os.close(descriptor)

    assert signals == [(4321, signal.SIGTERM)]


@pytest.mark.parametrize(
    ("recipe", "filter_fragment", "extra_argument"),
    [
        ("SIMULATED_IR", "format=gray", None),
        ("LOW_CONTRAST", "eq=contrast=0.5", None),
        ("BOUNDED_OCCLUSION", "drawbox=", None),
        ("SYNTHETIC_SCALE", "scale=iw*0.35:ih*0.35", None),
        ("LOOP_TO_MINIMUM", "scale=960:540", "-stream_loop"),
    ],
)
def test_only_fixed_derivative_recipes_are_rendered(
    tmp_path: Path,
    recipe: str,
    filter_fragment: str,
    extra_argument: str | None,
) -> None:
    module = prepare_module()
    corpus_layout = layout(tmp_path)
    source = source_file(corpus_layout)
    runner = RecordingRunner(
        valid_probe(codec="mjpeg", width=960, height=540, fps="5/1")
    )

    module.CorpusPreparer(
        layout=corpus_layout,
        profiles=(profile("analysis_realtime"),),
        source_resolver=lambda _source_id: source,
        runner=runner,
    ).prepare_clip(
        clip(
            clip_id=f"DAY-01-{recipe.replace('_', '-')}",
            recipe=recipe,
            parent_clip_id="DAY-01",
        )
    )

    argv = runner.output_calls[0][0]
    assert filter_fragment in " ".join(argv)
    if extra_argument is not None:
        assert extra_argument in argv


def test_missing_hevc_encoder_fails_without_output(tmp_path: Path) -> None:
    module = prepare_module()
    corpus_layout = layout(tmp_path)
    source = source_file(corpus_layout)
    runner = RecordingRunner()
    runner.supported.remove("libx265")

    with pytest.raises(
        module.CorpusPrepareError,
        match="^visual_corpus_hevc_encoder_unavailable$",
    ):
        module.CorpusPreparer(
            layout=corpus_layout,
            profiles=(profile(),),
            source_resolver=lambda _source_id: source,
            runner=runner,
        ).prepare_clip(clip())

    assert runner.output_calls == []
    assert list(corpus_layout.prepared.iterdir()) == []


def test_probe_mismatch_never_publishes(tmp_path: Path) -> None:
    module = prepare_module()
    corpus_layout = layout(tmp_path)
    source = source_file(corpus_layout)
    runner = RecordingRunner(valid_probe(width=1280, height=720))

    with pytest.raises(
        module.CorpusPrepareError,
        match="^visual_corpus_profile_mismatch$",
    ):
        module.CorpusPreparer(
            layout=corpus_layout,
            profiles=(profile(),),
            source_resolver=lambda _source_id: source,
            runner=runner,
        ).prepare_clip(clip())

    assert list(corpus_layout.prepared.iterdir()) == []


def test_prepare_validates_the_requested_clip_duration(tmp_path: Path) -> None:
    module = prepare_module()
    corpus_layout = layout(tmp_path)
    source = source_file(corpus_layout)
    runner = RecordingRunner(valid_probe(duration="20.000000"))

    prepared = module.CorpusPreparer(
        layout=corpus_layout,
        profiles=(profile(),),
        source_resolver=lambda _source_id: source,
        runner=runner,
    ).prepare_clip(clip(end_ms=22_000))

    assert prepared.artifacts[0].path.exists()
