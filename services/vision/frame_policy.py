from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from math import ceil, floor

from PIL import Image, ImageDraw, UnidentifiedImageError

from packages.contracts.vision import NormalizedPolygon
from services.stream.frame_source import CapturedFrame


OUTPUT_WIDTH = 960
OUTPUT_HEIGHT = 540
OUTPUT_JPEG_QUALITY = 80
MAX_OUTPUT_BYTES = 1024 * 1024
CROP_EXPANSION = 0.15


class FramePolicyError(ValueError):
    """A stable, non-sensitive visual frame policy failure."""


@dataclass(frozen=True)
class PreparedAnalysisFrame:
    jpeg: bytes
    captured_at: datetime
    width: int
    height: int
    crop_box: tuple[int, int, int, int]


class VisionFramePolicy:
    def __init__(
        self,
        *,
        bed_zone: NormalizedPolygon | None,
        privacy_masks: tuple[NormalizedPolygon, ...] = (),
    ) -> None:
        if bed_zone is None:
            raise FramePolicyError("VISUAL_BED_ZONE_REQUIRED")
        self._require_valid_polygon(bed_zone)
        for privacy_mask in privacy_masks:
            self._require_valid_polygon(privacy_mask)
        self._bed_zone = bed_zone
        self._privacy_masks = tuple(privacy_masks)

    @property
    def bed_zone(self) -> NormalizedPolygon:
        return self._bed_zone

    @property
    def privacy_masks(self) -> tuple[NormalizedPolygon, ...]:
        return self._privacy_masks

    def prepare(self, frame: CapturedFrame) -> PreparedAnalysisFrame:
        if frame.captured_at.tzinfo is None or frame.captured_at.utcoffset() is None:
            raise FramePolicyError("VISUAL_FRAME_INVALID")
        try:
            with Image.open(BytesIO(frame.jpeg)) as source:
                if source.format != "JPEG" or source.size != (frame.width, frame.height):
                    raise FramePolicyError("VISUAL_FRAME_INVALID")
                source.load()
                rgb = source.convert("RGB")
        except FramePolicyError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise FramePolicyError("VISUAL_FRAME_INVALID") from exc

        crop_box = self._expanded_crop_box(frame.width, frame.height)
        cropped = rgb.crop(crop_box)
        self._apply_privacy_masks(
            cropped,
            crop_box=crop_box,
            source_width=frame.width,
            source_height=frame.height,
        )
        prepared = cropped.resize(
            (OUTPUT_WIDTH, OUTPUT_HEIGHT),
            resample=Image.Resampling.LANCZOS,
        )
        output = BytesIO()
        prepared.save(
            output,
            format="JPEG",
            quality=OUTPUT_JPEG_QUALITY,
        )
        payload = output.getvalue()
        if len(payload) > MAX_OUTPUT_BYTES:
            raise FramePolicyError("VISUAL_FRAME_TOO_LARGE")
        return PreparedAnalysisFrame(
            jpeg=payload,
            captured_at=frame.captured_at,
            width=OUTPUT_WIDTH,
            height=OUTPUT_HEIGHT,
            crop_box=crop_box,
        )

    def _expanded_crop_box(
        self, source_width: int, source_height: int
    ) -> tuple[int, int, int, int]:
        xs = [point.x for point in self._bed_zone.points]
        ys = [point.y for point in self._bed_zone.points]
        left = min(xs) * source_width
        top = min(ys) * source_height
        right = max(xs) * source_width
        bottom = max(ys) * source_height
        horizontal_expansion = (right - left) * CROP_EXPANSION
        vertical_expansion = (bottom - top) * CROP_EXPANSION
        crop_box = (
            max(0, floor(left - horizontal_expansion)),
            max(0, floor(top - vertical_expansion)),
            min(source_width, ceil(right + horizontal_expansion)),
            min(source_height, ceil(bottom + vertical_expansion)),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            raise FramePolicyError("VISUAL_ZONE_INVALID")
        return crop_box

    def _apply_privacy_masks(
        self,
        image: Image.Image,
        *,
        crop_box: tuple[int, int, int, int],
        source_width: int,
        source_height: int,
    ) -> None:
        draw = ImageDraw.Draw(image)
        left, top, _, _ = crop_box
        for privacy_mask in self._privacy_masks:
            points = [
                (
                    round(point.x * source_width - left),
                    round(point.y * source_height - top),
                )
                for point in privacy_mask.points
            ]
            draw.polygon(points, fill=(0, 0, 0))

    @staticmethod
    def _require_valid_polygon(polygon: NormalizedPolygon) -> None:
        points = polygon.points
        if len(points) < 3 or len(set(points)) < 3:
            raise FramePolicyError("VISUAL_ZONE_INVALID")
        double_area = sum(
            first.x * second.y - second.x * first.y
            for first, second in zip(
                points,
                (*points[1:], points[0]),
                strict=True,
            )
        )
        if abs(double_area) <= 1e-9:
            raise FramePolicyError("VISUAL_ZONE_INVALID")
