from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts.vision import NormalizedPoint, NormalizedPolygon
from services.vision.frame_policy import FramePolicyError, VisionFramePolicy


def rectangle(
    left: float = 0.25,
    top: float = 0.2,
    right: float = 0.75,
    bottom: float = 0.8,
) -> NormalizedPolygon:
    return NormalizedPolygon(
        points=(
            NormalizedPoint(x=left, y=top),
            NormalizedPoint(x=right, y=top),
            NormalizedPoint(x=right, y=bottom),
            NormalizedPoint(x=left, y=bottom),
        )
    )


def test_valid_normalized_polygon_is_immutable_and_keeps_order() -> None:
    polygon = rectangle()

    assert polygon.points[0] == NormalizedPoint(x=0.25, y=0.2)
    assert polygon.points[-1] == NormalizedPoint(x=0.25, y=0.8)
    with pytest.raises(ValidationError, match="frozen"):
        polygon.points = ()


@pytest.mark.parametrize(
    ("x", "y"),
    [(-0.01, 0.5), (1.01, 0.5), (0.5, -0.01), (0.5, 1.01)],
)
def test_normalized_point_rejects_coordinates_outside_source(
    x: float, y: float
) -> None:
    with pytest.raises(ValidationError):
        NormalizedPoint(x=x, y=y)


def test_polygon_rejects_fewer_than_three_points() -> None:
    with pytest.raises(ValidationError):
        NormalizedPolygon(
            points=(
                NormalizedPoint(x=0.1, y=0.1),
                NormalizedPoint(x=0.9, y=0.9),
            )
        )


def test_polygon_rejects_fewer_than_three_distinct_points() -> None:
    repeated = NormalizedPoint(x=0.1, y=0.1)

    with pytest.raises(ValidationError, match="distinct"):
        NormalizedPolygon(points=(repeated, repeated, NormalizedPoint(x=0.9, y=0.9)))


def test_polygon_rejects_collinear_zero_area_geometry() -> None:
    with pytest.raises(ValidationError, match="non-zero area"):
        NormalizedPolygon(
            points=(
                NormalizedPoint(x=0.1, y=0.1),
                NormalizedPoint(x=0.5, y=0.5),
                NormalizedPoint(x=0.9, y=0.9),
            )
        )


def test_policy_requires_explicit_bed_zone() -> None:
    with pytest.raises(FramePolicyError, match="VISUAL_BED_ZONE_REQUIRED"):
        VisionFramePolicy(bed_zone=None)


def test_policy_accepts_multiple_valid_privacy_masks() -> None:
    policy = VisionFramePolicy(
        bed_zone=rectangle(),
        privacy_masks=(
            rectangle(0.0, 0.0, 0.1, 0.1),
            rectangle(0.9, 0.9, 1.0, 1.0),
        ),
    )

    assert policy.bed_zone == rectangle()
    assert len(policy.privacy_masks) == 2
