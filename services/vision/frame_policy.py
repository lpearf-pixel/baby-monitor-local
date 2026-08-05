from __future__ import annotations

from packages.contracts.vision import NormalizedPolygon


class FramePolicyError(ValueError):
    """A stable, non-sensitive visual frame policy failure."""


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
