from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.stream.frame_source import Go2RtcAnalysisFrameSource
from services.vision.frame_policy import VisionFramePolicy
from services.vision.realtime_analyzer import RealtimeVisualAnalyzer
from services.vision.realtime_models import (
    OpenVinoYuNetBackend,
    build_realtime_model_backend,
    decode_pose_maps,
)


STAGE_NAMES = (
    "frame_policy_excluded_from_metric",
    "jpeg_decode",
    "yunet_face",
    "pose_preprocess",
    "pose_inference",
    "pose_decode",
    "semantic_backend_total",
    "production_analyzer_total",
)

DiagnosticSamples = Mapping[str, Sequence[float]]
LiveRunner = Callable[[Path], DiagnosticSamples]


class DiagnosticStageError(RuntimeError):
    def __init__(self, reason: str, cause: Exception) -> None:
        super().__init__(reason)
        self.reason = reason
        self.__cause__ = cause


def _run_stage(reason: str, action: Callable[[], Any]) -> Any:
    try:
        return action()
    except DiagnosticStageError:
        raise
    except Exception as exc:
        raise DiagnosticStageError(reason, exc) from exc


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    if not values or not 0 < percentile <= 1:
        raise ValueError("diagnostic_samples_invalid")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("diagnostic_samples_invalid")
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def render_report(samples: DiagnosticSamples) -> str:
    if set(samples) != set(STAGE_NAMES):
        raise ValueError("diagnostic_samples_invalid")
    lines: list[str] = []
    for name in STAGE_NAMES:
        values = tuple(samples[name])
        p50 = statistics.median(values)
        p95 = nearest_rank_percentile(values, 0.95)
        maximum = max(values)
        lines.append(
            f"{name}: p50={p50:.3f}ms p95={p95:.3f}ms "
            f"max={maximum:.3f}ms"
        )
    lines.append("diagnostic=PASS")
    return "\n".join(lines)


def _measure(action: Callable[[], Any], count: int) -> tuple[float, ...]:
    values: list[float] = []
    for _ in range(count):
        started = time.perf_counter()
        action()
        values.append(max(0.0, (time.perf_counter() - started) * 1000))
    return tuple(values)


def _pose_tensor(bgr: np.ndarray) -> np.ndarray:
    resized = cv2.resize(bgr, (456, 256), interpolation=cv2.INTER_LINEAR)
    return np.transpose(resized, (2, 0, 1))[None].astype(np.float32)


def _pose_maps(outputs: Mapping[Any, Any]) -> tuple[np.ndarray, np.ndarray]:
    arrays = tuple(np.asarray(value) for value in outputs.values())
    heatmaps = next(
        value[0]
        for value in arrays
        if value.ndim == 4 and value.shape[1] == 19
    )
    pafs = next(
        value[0]
        for value in arrays
        if value.ndim == 4 and value.shape[1] == 38
    )
    return pafs, heatmaps


def run_live_diagnostic(settings_path: Path) -> DiagnosticSamples:
    settings = _run_stage(
        "settings_load_failed",
        lambda: AppSettings.load(settings_path),
    )
    if not settings.visual.enabled or not settings.visual.realtime.enabled:
        raise DiagnosticStageError(
            "diagnostic_unavailable",
            ValueError("visual realtime disabled"),
        )

    source = Go2RtcAnalysisFrameSource(
        base_url=(
            f"http://{settings.stream.go2rtc_api_host}:"
            f"{settings.stream.go2rtc_api_port}"
        ),
        stream_name="analysis_realtime",
    )
    frames = source.iter_frames(timeout_seconds=8)
    try:
        captured = _run_stage("frame_capture_failed", lambda: next(frames))
    finally:
        frames.close()

    policy = _run_stage(
        "frame_policy_failed",
        lambda: VisionFramePolicy(
            bed_zone=settings.visual.bed_zone,
            privacy_masks=settings.visual.privacy_masks,
        ),
    )
    policy_times = _run_stage(
        "frame_policy_failed",
        lambda: _measure(lambda: policy.prepare(captured), 8),
    )
    prepared = _run_stage(
        "frame_policy_failed",
        lambda: policy.prepare(captured),
    )

    encoded = np.frombuffer(prepared.jpeg, dtype=np.uint8)
    decode = lambda: cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    decode_times = _run_stage(
        "jpeg_decode_failed",
        lambda: _measure(decode, 20),
    )
    bgr = _run_stage("jpeg_decode_failed", decode)
    if bgr is None:
        raise DiagnosticStageError(
            "jpeg_decode_failed",
            ValueError("diagnostic frame invalid"),
        )

    model_root = settings.app.data_dir
    if not model_root.is_absolute():
        model_root = ROOT / model_root
    backend = _run_stage(
        "model_backend_unavailable",
        lambda: build_realtime_model_backend(
            model_root / "models/openvino-2025.4.1"
        ),
    )
    if not isinstance(backend, OpenVinoYuNetBackend):
        raise DiagnosticStageError(
            "model_backend_unavailable",
            ValueError("model backend unavailable"),
        )

    face_detector = backend._face_detector
    def measure_face() -> tuple[float, ...]:
        face_detector.setInputSize((bgr.shape[1], bgr.shape[0]))
        for _ in range(3):
            face_detector.detect(bgr)
        return _measure(lambda: face_detector.detect(bgr), 20)

    face_times = _run_stage("yunet_face_failed", measure_face)

    preprocess_times = _run_stage(
        "pose_preprocess_failed",
        lambda: _measure(lambda: _pose_tensor(bgr), 20),
    )
    tensor = _run_stage("pose_preprocess_failed", lambda: _pose_tensor(bgr))
    pose_model = backend._pose_model
    def measure_pose_inference() -> tuple[float, ...]:
        for _ in range(3):
            pose_model([tensor])
        return _measure(lambda: pose_model([tensor]), 20)

    inference_times = _run_stage(
        "pose_inference_failed",
        measure_pose_inference,
    )

    pafs, heatmaps = _run_stage(
        "pose_decode_failed",
        lambda: _pose_maps(pose_model([tensor])),
    )
    decode_pose_times = _run_stage(
        "pose_decode_failed",
        lambda: _measure(lambda: decode_pose_maps(pafs, heatmaps), 20),
    )

    def measure_backend() -> tuple[float, ...]:
        for _ in range(3):
            backend.infer(bgr)
        return _measure(lambda: backend.infer(bgr), 12)

    backend_times = _run_stage("semantic_backend_failed", measure_backend)

    analyzer = RealtimeVisualAnalyzer(model_backend=backend)
    analyzer_times = _run_stage(
        "production_analyzer_failed",
        lambda: _measure(
            lambda: analyzer.analyze(
                prepared,
                monotonic_now=time.monotonic(),
            ),
            12,
        ),
    )

    return {
        "frame_policy_excluded_from_metric": policy_times,
        "jpeg_decode": decode_times,
        "yunet_face": face_times,
        "pose_preprocess": preprocess_times,
        "pose_inference": inference_times,
        "pose_decode": decode_pose_times,
        "semantic_backend_total": backend_times,
        "production_analyzer_total": analyzer_times,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure redacted realtime visual stage timings."
    )
    parser.add_argument("--settings", required=True, type=Path)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    run: LiveRunner = run_live_diagnostic,
) -> int:
    args = parse_args(argv)
    try:
        print(render_report(run(args.settings)))
    except DiagnosticStageError as exc:
        print(f"diagnostic=FAIL reason={exc.reason}")
        return 2
    except Exception:
        print("diagnostic=FAIL reason=diagnostic_failed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
