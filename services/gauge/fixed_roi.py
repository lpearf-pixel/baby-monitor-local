from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from services.gauge.calibration import Ws2021Calibration
from services.gauge.locator import GaugeLocation
from services.stream.frame_source import CapturedFrame


class FixedRoiErrorCode(StrEnum):
    CALIBRATION_INVALID = "fixed_roi_calibration_invalid"
    SOURCE_DRIFT = "fixed_roi_source_drift"
    OUT_OF_FRAME = "fixed_roi_out_of_frame"
    TOO_SMALL = "fixed_roi_too_small"


class FixedRoiError(RuntimeError):
    """A bounded, safe failure from fixed-ROI localization."""

    def __init__(self, code: FixedRoiErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True)
class FixedRoiSettings:
    max_dimension_drift_fraction: float = 0.05
    min_width_pixels: int = 64
    min_height_pixels: int = 64
    model_version: str = "fixed-roi-v1"

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_dimension_drift_fraction) or not (
            0 <= self.max_dimension_drift_fraction < 1
        ):
            raise ValueError("max_dimension_drift_fraction must be in [0, 1)")
        if self.min_width_pixels <= 0 or self.min_height_pixels <= 0:
            raise ValueError("minimum ROI dimensions must be positive")
        if not self.model_version:
            raise ValueError("model_version must not be empty")


class FixedRoiLocator:
    """Derive a bounded, normalized WS2021 location from schema-v2 calibration."""

    def __init__(
        self,
        calibration: Ws2021Calibration,
        *,
        settings: FixedRoiSettings | None = None,
    ) -> None:
        self._calibration = calibration
        self._settings = settings or FixedRoiSettings()

    def locate(self, frame: CapturedFrame) -> GaugeLocation:
        calibration = self._calibration
        try:
            if not isinstance(calibration, Ws2021Calibration):
                raise ValueError
            source_width = calibration.source_width
            source_height = calibration.source_height
            rect = calibration.gauge_rect
            values = (
                source_width,
                source_height,
                rect.x,
                rect.y,
                rect.width,
                rect.height,
            )
            if not all(math.isfinite(float(value)) for value in values):
                raise ValueError
        except Exception as exc:
            raise FixedRoiError(FixedRoiErrorCode.CALIBRATION_INVALID) from exc

        if frame.width <= 0 or frame.height <= 0:
            raise FixedRoiError(FixedRoiErrorCode.OUT_OF_FRAME)
        width_drift = abs(frame.width - source_width) / source_width
        height_drift = abs(frame.height - source_height) / source_height
        if max(width_drift, height_drift) > self._settings.max_dimension_drift_fraction:
            raise FixedRoiError(FixedRoiErrorCode.SOURCE_DRIFT)

        right = rect.x + rect.width
        bottom = rect.y + rect.height
        if rect.x < 0 or rect.y < 0 or right > 1 or bottom > 1:
            raise FixedRoiError(FixedRoiErrorCode.OUT_OF_FRAME)
        if (
            rect.width * frame.width < self._settings.min_width_pixels
            or rect.height * frame.height < self._settings.min_height_pixels
        ):
            raise FixedRoiError(FixedRoiErrorCode.TOO_SMALL)

        try:
            return GaugeLocation(
                box=rect,
                confidence=1.0,
                model_version=self._settings.model_version,
            )
        except Exception as exc:
            raise FixedRoiError(FixedRoiErrorCode.CALIBRATION_INVALID) from exc


class StableFixedRoiLocator:
    """Release fixed-ROI locations only after a bounded valid-frame run."""

    _MAX_REQUIRED_CONSECUTIVE_FRAMES = 60

    def __init__(
        self,
        locator: FixedRoiLocator,
        *,
        required_consecutive_frames: int = 3,
    ) -> None:
        if isinstance(required_consecutive_frames, bool) or not (
            1 <= required_consecutive_frames <= self._MAX_REQUIRED_CONSECUTIVE_FRAMES
        ):
            raise ValueError("required_consecutive_frames must be between 1 and 60")
        self._locator = locator
        self._required_consecutive_frames = required_consecutive_frames
        self._valid_count = 0
        self._latest_location: GaugeLocation | None = None

    def observe(self, frame: CapturedFrame) -> GaugeLocation | None:
        try:
            location = self._locator.locate(frame)
        except FixedRoiError:
            self._valid_count = 0
            self._latest_location = None
            return None

        self._valid_count = min(
            self._valid_count + 1,
            self._required_consecutive_frames,
        )
        self._latest_location = location
        if self._valid_count < self._required_consecutive_frames:
            return None
        return self._latest_location
