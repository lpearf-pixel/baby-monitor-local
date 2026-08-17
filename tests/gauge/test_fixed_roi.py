from __future__ import annotations

import gc
import weakref

import pytest

from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation
from services.stream.frame_source import CapturedFrame
from tests.gauge.synthetic_dial import calibration, frame_jpeg


def _frame(width: int = 640, height: int = 480) -> CapturedFrame:
    return CapturedFrame(
        jpeg=frame_jpeg(),
        captured_at=calibration().created_at,
        width=width,
        height=height,
    )


def _lower_right_calibration():
    from services.gauge.relocation import relocate_calibration

    return relocate_calibration(
        calibration(),
        GaugeLocation(
            box=NormalizedRect(x=0.60, y=0.20, width=0.35, height=0.70),
            confidence=1.0,
            model_version="test-v1",
        ),
    )


def test_fixed_roi_derives_lower_right_normalized_location() -> None:
    from services.gauge.fixed_roi import FixedRoiLocator

    location = FixedRoiLocator(_lower_right_calibration()).locate(_frame())

    assert location.box == _lower_right_calibration().gauge_rect
    assert location.box.x > 0.5
    assert location.box.y < 0.5
    assert location.confidence == 1.0
    assert location.model_version == "fixed-roi-v1"


def test_fixed_roi_accepts_small_source_dimension_drift() -> None:
    from services.gauge.fixed_roi import FixedRoiLocator, FixedRoiSettings

    locator = FixedRoiLocator(
        _lower_right_calibration(),
        settings=FixedRoiSettings(max_dimension_drift_fraction=0.05),
    )

    location = locator.locate(_frame(width=650, height=485))

    assert location.box.x == pytest.approx(_lower_right_calibration().gauge_rect.x)


def test_fixed_roi_rejects_source_dimensions_outside_bounded_drift() -> None:
    from services.gauge.fixed_roi import FixedRoiError, FixedRoiErrorCode, FixedRoiLocator

    with pytest.raises(FixedRoiError) as caught:
        FixedRoiLocator(_lower_right_calibration()).locate(_frame(width=800, height=480))

    assert caught.value.code is FixedRoiErrorCode.SOURCE_DRIFT


def test_fixed_roi_rejects_out_of_frame_geometry() -> None:
    from services.gauge.fixed_roi import FixedRoiError, FixedRoiErrorCode, FixedRoiLocator

    malformed = _lower_right_calibration().model_copy(
        update={
            "gauge_rect": NormalizedRect.model_construct(
                x=0.8, y=0.2, width=0.3, height=0.5
            )
        }
    )

    with pytest.raises(FixedRoiError) as caught:
        FixedRoiLocator(malformed).locate(_frame())

    assert caught.value.code is FixedRoiErrorCode.OUT_OF_FRAME


def test_fixed_roi_rejects_too_small_calibrated_geometry() -> None:
    from services.gauge.fixed_roi import FixedRoiError, FixedRoiErrorCode, FixedRoiLocator, FixedRoiSettings

    tiny = _lower_right_calibration().model_copy(
        update={"gauge_rect": NormalizedRect(x=0.8, y=0.8, width=0.05, height=0.05)}
    )

    with pytest.raises(FixedRoiError) as caught:
        FixedRoiLocator(
            tiny,
            settings=FixedRoiSettings(min_width_pixels=64, min_height_pixels=64),
        ).locate(_frame())

    assert caught.value.code is FixedRoiErrorCode.TOO_SMALL


def test_fixed_roi_rejects_malformed_calibration_fail_closed() -> None:
    from services.gauge.fixed_roi import FixedRoiError, FixedRoiErrorCode, FixedRoiLocator

    malformed = _lower_right_calibration().model_copy(
        update={"gauge_rect": {"x": 0.9, "y": 0.9, "width": 0.5, "height": 0.5}}
    )

    with pytest.raises(FixedRoiError) as caught:
        FixedRoiLocator(malformed).locate(_frame())

    assert caught.value.code is FixedRoiErrorCode.CALIBRATION_INVALID


def test_stable_fixed_roi_requires_consecutive_valid_frames() -> None:
    from services.gauge.fixed_roi import FixedRoiLocator, StableFixedRoiLocator

    stable = StableFixedRoiLocator(
        FixedRoiLocator(_lower_right_calibration()),
        required_consecutive_frames=3,
    )

    assert stable.observe(_frame()) is None
    assert stable.observe(_frame()) is None
    location = stable.observe(_frame())

    assert location is not None
    assert location.box == _lower_right_calibration().gauge_rect


def test_stable_fixed_roi_resets_after_one_invalid_frame() -> None:
    from services.gauge.fixed_roi import FixedRoiLocator, StableFixedRoiLocator

    stable = StableFixedRoiLocator(
        FixedRoiLocator(_lower_right_calibration()),
        required_consecutive_frames=3,
    )

    assert stable.observe(_frame()) is None
    assert stable.observe(_frame(width=800)) is None
    assert stable.observe(_frame()) is None
    assert stable.observe(_frame()) is None
    assert stable.observe(_frame()) is not None


def test_stable_fixed_roi_does_not_retain_frames() -> None:
    from services.gauge.fixed_roi import FixedRoiLocator, StableFixedRoiLocator

    stable = StableFixedRoiLocator(
        FixedRoiLocator(_lower_right_calibration()),
        required_consecutive_frames=2,
    )
    frame = _frame()
    reference = weakref.ref(frame)

    assert stable.observe(frame) is None
    del frame
    gc.collect()

    assert reference() is None
