from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from packages.monitoring.realtime_models import ModelAssetCode, ModelAssetStatus

from services.vision.realtime_models import (
    OpenVinoYuNetBackend,
    RealtimeModelError,
    RealtimeModelSignals,
    build_realtime_model_backend,
    decode_pose_maps,
)


def test_model_signals_are_bounded_process_local_values() -> None:
    signals = RealtimeModelSignals(
        face_boxes=((0.1, 0.2, 0.3, 0.4),),
        pose_centers=((0.5, 0.6),),
        torso_angles=(32.0,),
    )

    assert signals.face_boxes[0] == (0.1, 0.2, 0.3, 0.4)
    assert signals.pose_centers[0] == (0.5, 0.6)
    assert "image" not in repr(signals).lower()


def test_model_signals_reject_nonfinite_or_out_of_bounds_geometry() -> None:
    invalid = (
        {"face_boxes": ((-0.1, 0.2, 0.3, 0.4),)},
        {"pose_centers": ((1.1, 0.5),)},
        {"torso_angles": (float("nan"),)},
    )
    for values in invalid:
        try:
            RealtimeModelSignals(**values)
        except ValueError as exc:
            assert str(exc) == "realtime_model_output_invalid"
        else:
            raise AssertionError("invalid model signal was accepted")


def test_missing_assets_return_no_backend_without_importing_openvino(
    tmp_path: Path,
) -> None:
    assert build_realtime_model_backend(tmp_path) is None


def test_official_openvino_build_suffix_is_accepted(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from services.vision import realtime_models

    expected_backend = object()
    monkeypatch.setattr(
        realtime_models,
        "verify_realtime_model_assets",
        lambda _root: ModelAssetStatus(ModelAssetCode.OK, 3),
    )
    monkeypatch.setitem(
        sys.modules,
        "openvino",
        SimpleNamespace(
            __version__=(
                "2025.4.1-20426-82bbf0292c5-releases/2025/4"
            )
        ),
    )
    monkeypatch.setattr(
        realtime_models,
        "OpenVinoYuNetBackend",
        lambda _root, _openvino: expected_backend,
    )

    assert build_realtime_model_backend(tmp_path) is expected_backend


def test_backend_error_is_stable_and_redacted() -> None:
    error = RealtimeModelError("realtime_inference_failed")

    assert str(error) == "realtime_inference_failed"
    assert "/private" not in repr(error)


def test_signal_contract_accepts_real_bgr_shape_without_retaining_frame() -> None:
    image = np.zeros((32, 48, 3), dtype=np.uint8)
    signals = RealtimeModelSignals()

    assert image.shape == (32, 48, 3)
    assert signals.face_boxes == ()
    assert not hasattr(signals, "image")


def test_pose_decoder_groups_people_with_pafs_and_ignores_orphan_peaks() -> None:
    pafs, heatmaps = _pose_maps()

    heatmaps[1, 29, 27] = 0.99
    centers, torso_angles = decode_pose_maps(pafs, heatmaps)

    assert len(centers) == 2
    assert centers[0][0] < centers[1][0]
    assert all(0.0 <= value <= 1.0 for center in centers for value in center)
    assert len(torso_angles) == 2
    assert all(70.0 <= angle <= 100.0 for angle in torso_angles)


def test_pose_decoder_rejects_nonfinite_model_tensors() -> None:
    for tensor_name, value in (
        ("pafs", float("nan")),
        ("pafs", float("inf")),
        ("pafs", float("-inf")),
        ("heatmaps", float("nan")),
        ("heatmaps", float("inf")),
        ("heatmaps", float("-inf")),
    ):
        pafs, heatmaps = _pose_maps()
        tensor = pafs if tensor_name == "pafs" else heatmaps
        tensor[0, 0, 0] = value

        try:
            decode_pose_maps(pafs, heatmaps)
        except ValueError as exc:
            assert str(exc) == "realtime_model_output_invalid"
        else:
            raise AssertionError(f"accepted nonfinite {tensor_name}")


def test_backend_wraps_nonfinite_pose_output_as_stable_error() -> None:
    pafs, heatmaps = _pose_maps()
    pafs[0, 0, 0] = float("inf")
    backend = object.__new__(OpenVinoYuNetBackend)
    backend._face_detector = _FakeFaceDetector()
    backend._pose_model = _FakePoseModel(pafs, heatmaps)

    try:
        backend.infer(np.zeros((540, 960, 3), dtype=np.uint8))
    except RealtimeModelError as exc:
        assert str(exc) == "realtime_inference_failed"
        assert repr(exc) == "RealtimeModelError('realtime_inference_failed')"
    else:
        raise AssertionError("backend accepted nonfinite pose output")


def _pose_maps() -> tuple[np.ndarray, np.ndarray]:
    heatmaps = np.zeros((19, 32, 57), dtype=np.float32)
    pafs = np.zeros((38, 32, 57), dtype=np.float32)
    for neck, shoulder, hip in (
        ((10, 8), (15, 10), (11, 22)),
        ((38, 7), (44, 10), (39, 23)),
    ):
        heatmaps[1, neck[1], neck[0]] = 1.0
        heatmaps[2, shoulder[1], shoulder[0]] = 1.0
        heatmaps[8, hip[1], hip[0]] = 1.0
        _draw_paf(pafs, 12, 13, neck, shoulder)
        _draw_paf(pafs, 0, 1, neck, hip)
    return pafs, heatmaps


class _FakeFaceDetector:
    def setInputSize(self, size: tuple[int, int]) -> None:
        return None

    def detect(self, bgr: np.ndarray) -> tuple[None, None]:
        return None, None


class _FakePoseModel:
    def __init__(self, pafs: np.ndarray, heatmaps: np.ndarray) -> None:
        self._pafs = pafs
        self._heatmaps = heatmaps

    def __call__(self, inputs: list[np.ndarray]) -> dict[str, np.ndarray]:
        return {
            "pafs": self._pafs[None],
            "heatmaps": self._heatmaps[None],
        }


def _draw_paf(
    pafs: np.ndarray,
    x_channel: int,
    y_channel: int,
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    direction = np.asarray(end, dtype=np.float32) - np.asarray(
        start,
        dtype=np.float32,
    )
    direction /= np.linalg.norm(direction)
    for ratio in np.linspace(0.0, 1.0, 20):
        point = np.rint(
            np.asarray(start) + ratio * (np.asarray(end) - np.asarray(start))
        ).astype(int)
        x, y = int(point[0]), int(point[1])
        pafs[x_channel, max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (
            direction[0]
        )
        pafs[y_channel, max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (
            direction[1]
        )
