from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest
from pydantic import ValidationError
from PIL import Image, ImageDraw

from packages.contracts.vision import NormalizedPoint, NormalizedPolygon
from services.vision.frame_policy import FramePolicyError, VisionFramePolicy
from services.stream.frame_source import CapturedFrame


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


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


def quadrant_jpeg() -> bytes:
    image = Image.new("RGB", (200, 100), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 99, 49), fill=(255, 0, 0))
    draw.rectangle((100, 0, 199, 49), fill=(0, 255, 0))
    draw.rectangle((0, 50, 99, 99), fill=(0, 0, 255))
    draw.rectangle((100, 50, 199, 99), fill=(255, 255, 0))
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def captured_frame(
    *,
    jpeg: bytes | None = None,
    captured_at: datetime = NOW,
    width: int = 200,
    height: int = 100,
) -> CapturedFrame:
    return CapturedFrame(
        jpeg=jpeg if jpeg is not None else quadrant_jpeg(),
        captured_at=captured_at,
        width=width,
        height=height,
    )


def test_prepare_expands_bed_crop_masks_before_resize_and_bounds_output() -> None:
    policy = VisionFramePolicy(
        bed_zone=rectangle(),
        privacy_masks=(rectangle(0.25, 0.2, 0.5, 0.5),),
    )

    prepared = policy.prepare(captured_frame())

    assert prepared.crop_box == (35, 11, 165, 89)
    assert prepared.captured_at == NOW
    assert prepared.width == 960
    assert prepared.height == 540
    assert len(prepared.jpeg) <= 1024 * 1024
    with Image.open(BytesIO(prepared.jpeg)) as image:
        assert image.format == "JPEG"
        assert image.size == (960, 540)
        masked_pixel = image.getpixel((295, 166))
        green_control = image.getpixel((665, 166))

    assert max(masked_pixel) < 20
    assert green_control[1] > green_control[0] + 80
    assert green_control[1] > green_control[2] + 80


def test_prepare_rejects_malformed_jpeg_with_stable_error() -> None:
    policy = VisionFramePolicy(bed_zone=rectangle())

    with pytest.raises(FramePolicyError, match="VISUAL_FRAME_INVALID"):
        policy.prepare(captured_frame(jpeg=b"not-jpeg"))


def test_prepare_rejects_declared_dimension_mismatch() -> None:
    policy = VisionFramePolicy(bed_zone=rectangle())

    with pytest.raises(FramePolicyError, match="VISUAL_FRAME_INVALID"):
        policy.prepare(captured_frame(width=201))


def test_prepare_rejects_naive_capture_time() -> None:
    policy = VisionFramePolicy(bed_zone=rectangle())

    with pytest.raises(FramePolicyError, match="VISUAL_FRAME_INVALID"):
        policy.prepare(captured_frame(captured_at=datetime(2026, 8, 5, 12, 0)))
