from __future__ import annotations

import hashlib
import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from packages.contracts.private_visual_overlay import PrivateOverlayDescriptor
from packages.contracts.vision import RealtimeObservation
from packages.contracts.visual_corpus import VisualCorpusClip
from services.stream.file_frame_source import FileFrameSourceUnavailable
from services.stream.frame_source import CapturedFrame
from services.vision.realtime_analyzer import RealtimeVisualAnalyzer
from services.vision.realtime_models import RealtimeModelError, RealtimeModelSignals


STARTED_AT = datetime(2026, 8, 28, tzinfo=UTC)
PRIVATE_ASSET_ID = "plc-0123456789abcdef0123456789abcdef"
SECOND_PRIVATE_ASSET_ID = "plc-fedcba9876543210fedcba9876543210"


def replay_module():
    return importlib.import_module("services.vision.corpus_replay")


def private_asset():
    payload = b"synthetic-private-replay"
    return PrivateOverlayDescriptor.model_validate(
        {
            "schema_version": 1,
            "source_type": "PRIVATE_LOCAL_CAPTURE",
            "assets": [
                {
                    "private_asset_id": PRIVATE_ASSET_ID,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                    "duration_ms": 25_000,
                    "codec": "hevc",
                    "width": 2560,
                    "height": 1440,
                    "fps": 10.0,
                    "scenario_ids": ["WIDE-02", "NEG-01"],
                    "authorization_review": "approved",
                    "privacy_review": "approved",
                }
            ],
        }
    ).assets[0]


def test_private_asset_projects_one_ephemeral_clip_with_all_scenario_groups() -> None:
    module = replay_module()
    asset = private_asset()

    projections = module.private_replay_projections(
        (asset,),
        mapping={PRIVATE_ASSET_ID: "asset.mp4"},
    )

    assert len(projections) == 1
    assert projections[0].clip_id == PRIVATE_ASSET_ID
    assert projections[0].groups == (
        "scenario:NEG-01",
        "scenario:WIDE-02",
    )


@pytest.mark.parametrize("duplicate", ["digest", "mapping"])
def test_private_projection_rejects_two_clip_identities_for_one_backing(
    duplicate: str,
) -> None:
    module = replay_module()
    first = private_asset()
    second = first.model_copy(
        update={
            "private_asset_id": SECOND_PRIVATE_ASSET_ID,
            "sha256": (
                first.sha256
                if duplicate == "digest"
                else hashlib.sha256(b"second-synthetic-private-replay").hexdigest()
            ),
        }
    )
    mapping = {
        PRIVATE_ASSET_ID: "asset.mp4",
        SECOND_PRIVATE_ASSET_ID: (
            "asset.mp4" if duplicate == "mapping" else "second.mp4"
        ),
    }

    with pytest.raises(
        module.PrivateReplayProjectionError,
        match="private_overlay_duplicate_clip",
    ):
        module.private_replay_projections((first, second), mapping=mapping)


def clip(clip_id: str = "DAY-01", *, duration_ms: int = 12_000) -> VisualCorpusClip:
    return VisualCorpusClip.model_validate(
        {
            "clip_id": clip_id,
            "source_id": "public-source",
            "source_type": "PUBLIC_DATASET",
            "scenario_ids": ["DAY-01"],
            "start_ms": 0,
            "end_ms": duration_ms,
            "recipe": {"kind": "SOURCE_SEGMENT"},
            "labels": {
                "framing": "medium",
                "subject_scale": "medium",
                "subject_frame_area_ratio": 0.3,
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
    )


def jpeg(index: int, *, valid: bool = True) -> bytes:
    if not valid:
        return b"not-a-jpeg"
    image = Image.new("RGB", (320, 180), (70, 80, 90))
    draw = ImageDraw.Draw(image)
    for y in range(0, 180, 10):
        for x in range(0, 320, 10):
            shade = 220 if (x // 10 + y // 10) % 2 else 30
            draw.rectangle((x, y, x + 9, y + 9), fill=(shade, shade, shade))
    draw.rectangle((20 + index % 8, 20, 100 + index % 8, 100), fill=(210, 180, 90))
    output = BytesIO()
    image.save(output, format="JPEG", quality=85)
    return output.getvalue()


def frames(count: int, *, invalid_at: int | None = None) -> tuple[CapturedFrame, ...]:
    return tuple(
        CapturedFrame(
            jpeg=jpeg(index, valid=index != invalid_at),
            captured_at=STARTED_AT + timedelta(seconds=index / 5),
            width=320,
            height=180,
        )
        for index in range(count)
    )


class FakeSource:
    def __init__(
        self,
        values: tuple[CapturedFrame, ...],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.values = values
        self.failure = failure

    def iter_frames(self, *, started_at: datetime, pace: bool = False):
        assert pace is False
        for index, frame in enumerate(self.values):
            yield replace(
                frame,
                captured_at=started_at + timedelta(seconds=index / 5),
            )
        if self.failure is not None:
            raise self.failure


class AvailableBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        return RealtimeModelSignals(
            face_boxes=((0.4, 0.3, 0.2, 0.2),),
            pose_centers=((0.5, 0.5),),
        )


class DegradingBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        raise RealtimeModelError("private backend detail")


class FailingAnalyzer:
    model_state = "available"

    def analyze(self, _frame: object, *, monotonic_now: float) -> RealtimeObservation:
        raise RuntimeError("private model path")

    def pop_health_transition(self) -> None:
        return None


def profile(*, backend: object | None = None, require_model: bool = True):
    module = replay_module()
    return module.ReplayProfile(
        profile_id="analysis_realtime",
        fps=5,
        model_backend=backend,
        require_model=require_model,
    )


def build_replay(
    tmp_path: Path,
    source: FakeSource,
    *,
    analyzer_factory=None,
):
    module = replay_module()
    media = tmp_path / "prepared.mkv"
    media.write_bytes(b"fixture")
    return module.VisualCorpusReplay(
        prepared_resolver=lambda _clip, _profile: media,
        source_factory=lambda _path, _fps: source,
        analyzer_factory=(
            analyzer_factory
            or (
                lambda replay_profile: RealtimeVisualAnalyzer(
                    model_backend=replay_profile.model_backend
                )
            )
        ),
    )


def test_replay_uses_real_worker_and_returns_bounded_aggregates(
    tmp_path: Path,
) -> None:
    module = replay_module()
    replay = build_replay(tmp_path, FakeSource(frames(60)))

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.frames_total == 60
    assert result.frames_processed + result.frames_skipped == 60
    assert result.observation_counts["pose_count.1"] == 60
    assert result.observation_counts["face_count.1"] == 60
    assert result.observation_counts["bed_subject_track.inside"] == 60
    assert result.observation_counts["adult_track.absent"] == 60
    assert result.observation_counts["head_face_state.visible"] == 60
    assert result.model_state == "available"
    assert 0 <= result.processing_p50_ms <= result.processing_p95_ms
    assert result.processing_p95_ms <= result.processing_max_ms
    assert 0 <= result.pipeline_p50_ms <= result.pipeline_p95_ms
    assert result.pipeline_p95_ms <= result.pipeline_max_ms
    assert result.frame_observations_persisted is False
    assert not hasattr(result, "frame_observations")
    assert sum(result.candidate_counts.values()) <= 60
    assert {
        "framing:medium",
        "scale:medium",
        "lighting:day",
        "visibility:full",
        "wide_role:none",
        "framing:medium+lighting:day",
        "scale:medium+visibility:full",
    }.issubset(result.groups)
    assert isinstance(replay.last_recording_analyzer, module.RecordingRealtimeAnalyzer)


def test_required_unavailable_model_skips_before_opening_media(tmp_path: Path) -> None:
    called: list[object] = []
    module = replay_module()
    replay = module.VisualCorpusReplay(
        prepared_resolver=lambda *_args: called.append("resolver"),
        source_factory=lambda *_args: called.append("source"),
    )

    result = replay.run_clip(clip(), profile=profile(backend=None))

    assert result.status == "SKIP"
    assert result.reason == "visual_corpus_model_unavailable"
    assert result.model_state == "unavailable"
    assert called == []


def test_decode_failure_is_not_reported_as_zero_risk_success(tmp_path: Path) -> None:
    replay = build_replay(
        tmp_path,
        FakeSource(
            frames(2),
            failure=FileFrameSourceUnavailable("file_decoder_failed"),
        ),
    )

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_decode_failed"
    assert result.decode_errors == 1
    assert result.frames_total == 2


def test_analysis_exception_fails_closed_with_no_raw_error(tmp_path: Path) -> None:
    replay = build_replay(
        tmp_path,
        FakeSource(frames(2)),
        analyzer_factory=lambda _profile: FailingAnalyzer(),
    )

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_analysis_failed"
    assert result.worker_errors == 1
    assert "private" not in repr(result)


def test_worker_policy_failure_is_counted_and_fails_closed(tmp_path: Path) -> None:
    replay = build_replay(tmp_path, FakeSource(frames(2, invalid_at=0)))

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_worker_failed"
    assert result.worker_errors == 1
    assert result.frames_total == 1
    assert result.frames_skipped == 1


def test_invalid_prepared_identity_is_redacted_and_never_opens_source(
    tmp_path: Path,
) -> None:
    module = replay_module()
    source_calls: list[object] = []

    def fail_resolver(_clip: object, _profile: object) -> Path:
        raise OSError("/private/household/clip")

    replay = module.VisualCorpusReplay(
        prepared_resolver=fail_resolver,
        source_factory=lambda *_args: source_calls.append("called"),
    )

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_input_invalid"
    assert source_calls == []
    assert "private" not in repr(result)


def test_each_clip_gets_fresh_analyzer_candidate_and_load_state(tmp_path: Path) -> None:
    analyzers: list[RealtimeVisualAnalyzer] = []

    def analyzer_factory(replay_profile):
        analyzer = RealtimeVisualAnalyzer(model_backend=replay_profile.model_backend)
        analyzers.append(analyzer)
        return analyzer

    replay = build_replay(
        tmp_path,
        FakeSource(frames(2)),
        analyzer_factory=analyzer_factory,
    )
    selected = profile(backend=AvailableBackend())

    first = replay.run_clip(clip("DAY-01"), profile=selected)
    second = replay.run_clip(clip("DAY-02"), profile=selected)

    assert first.status == second.status == "PASS"
    assert len(analyzers) == 2
    assert analyzers[0] is not analyzers[1]


def test_required_model_degradation_fails_closed_without_private_detail(
    tmp_path: Path,
) -> None:
    replay = build_replay(tmp_path, FakeSource(frames(2)))

    result = replay.run_clip(clip(), profile=profile(backend=DegradingBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_model_degraded"
    assert result.model_state == "degraded"
    assert "private" not in repr(result)


def test_result_frame_bound_fails_closed_with_valid_accounting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = replay_module()
    monkeypatch.setattr(module, "MAX_REPLAY_FRAMES", 2)
    replay = build_replay(tmp_path, FakeSource(frames(3)))

    result = replay.run_clip(clip(), profile=profile(backend=AvailableBackend()))

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_result_overflow"
    assert result.frames_total == 3
    assert result.frames_processed == 2
    assert result.frames_skipped == 1
