from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


def calibration_module():
    return importlib.import_module("services.gauge.calibration")


def test_cross_zero_scale_interpolates_without_extrapolation(
    calibration_data: dict[str, object],
) -> None:
    module = calibration_module()
    calibration = module.Ws2021Calibration.model_validate(calibration_data)

    assert calibration.humidity.value_for_angle(0.0) == pytest.approx(40.0)
    assert calibration.humidity.value_for_angle(20.0) == pytest.approx(60.0)
    assert calibration.humidity.value_for_angle(40.0) is None
    assert calibration.humidity.value_for_angle(340.0) is None


def test_viewport_points_are_reversed_to_source_coordinates() -> None:
    module = calibration_module()

    point = module.viewport_to_source(
        module.Point(x=0.5, y=0.5),
        zoom=2,
        center_x=0.25,
        center_y=0.5,
    )

    assert point == module.Point(x=0.25, y=0.5)


def test_viewport_mapping_clamps_the_visible_window_at_source_edges() -> None:
    module = calibration_module()

    top_left = module.viewport_to_source(
        module.Point(x=0, y=0), zoom=3, center_x=0, center_y=0
    )
    bottom_right = module.viewport_to_source(
        module.Point(x=1, y=1), zoom=3, center_x=1, center_y=1
    )

    assert top_left == module.Point(x=0, y=0)
    assert bottom_right == module.Point(x=1, y=1)


def test_calibration_rejects_degenerate_quadrilateral(
    calibration_data: dict[str, object],
) -> None:
    module = calibration_module()
    quadrilateral = calibration_data["gauge_quadrilateral"]
    assert isinstance(quadrilateral, dict)
    quadrilateral["bottom_left"] = {"x": 0.8, "y": 0.2}

    with pytest.raises(ValidationError, match="non-degenerate"):
        module.Ws2021Calibration.model_validate(calibration_data)


def test_calibration_rejects_face_points_outside_gauge_rect(
    calibration_data: dict[str, object],
) -> None:
    module = calibration_module()
    humidity = calibration_data["humidity"]
    assert isinstance(humidity, dict)
    humidity["center"] = {"x": 0.1, "y": 0.1}

    with pytest.raises(ValidationError, match="inside gauge_rect"):
        module.Ws2021Calibration.model_validate(calibration_data)


def test_calibration_rejects_duplicate_or_non_monotonic_scale_marks(
    calibration_data: dict[str, object],
) -> None:
    module = calibration_module()
    humidity = calibration_data["humidity"]
    assert isinstance(humidity, dict)
    marks = humidity["scale_marks"]
    assert isinstance(marks, list)
    second = marks[1]
    assert isinstance(second, dict)
    second["angle_degrees"] = 350
    second["unwrapped_angle_degrees"] = 350

    with pytest.raises(ValidationError, match="strictly increasing"):
        module.Ws2021Calibration.model_validate(calibration_data)


def test_calibration_rejects_extra_client_paths(
    calibration_data: dict[str, object],
) -> None:
    module = calibration_module()
    calibration_data["reference_path"] = "/private/family/gauge.jpg"

    with pytest.raises(ValidationError, match="Extra inputs"):
        module.Ws2021Calibration.model_validate(calibration_data)
