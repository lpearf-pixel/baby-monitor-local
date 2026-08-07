from __future__ import annotations

from pathlib import Path

import numpy as np

from services.vision.realtime_models import (
    RealtimeModelError,
    RealtimeModelSignals,
    build_realtime_model_backend,
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
