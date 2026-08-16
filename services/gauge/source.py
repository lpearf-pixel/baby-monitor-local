from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable, Protocol
from uuid import uuid4

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.gauge.calibration import (
    CalibrationInvalid,
    CalibrationMissing,
    Ws2021Calibration,
)
from services.gauge.locator import GaugeLocation
from services.gauge.relocation import refine_calibration
from services.stream.frame_source import (
    CapturedFrame,
    FrameBurst,
    FrameSourceUnavailable,
)


class EnvironmentReadingSource(Protocol):
    @property
    def source_kind(self) -> EnvironmentSourceKind: ...

    def read(self, requested_at: datetime) -> EnvironmentReading: ...


class ControlledFrameSource(Protocol):
    def capture_burst(
        self,
        *,
        frame_count: int,
        interval_ms: int,
        timeout_seconds: float,
    ) -> FrameBurst: ...


class GaugeCalibrationStore(Protocol):
    def current(self) -> Ws2021Calibration: ...


class Ws2021ReadingAlgorithm(Protocol):
    def read(
        self,
        burst: FrameBurst,
        calibration: Ws2021Calibration,
        requested_at: datetime,
    ) -> EnvironmentReading: ...


class GaugeLocationAlgorithm(Protocol):
    def locate(self, frame: CapturedFrame) -> GaugeLocation: ...


class Ws2021GaugeSource:
    def __init__(
        self,
        *,
        frame_source: ControlledFrameSource,
        calibration_store: GaugeCalibrationStore,
        reader: Ws2021ReadingAlgorithm,
        burst_frames: int = 5,
        burst_interval_ms: int = 500,
        burst_timeout_seconds: float = 8,
        freshness_seconds: int = 90,
        locator: GaugeLocationAlgorithm | None = None,
        relocator: Callable[
            [Ws2021Calibration, GaugeLocation, CapturedFrame], Ws2021Calibration
        ] = refine_calibration,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._frame_source = frame_source
        self._calibration_store = calibration_store
        self._reader = reader
        self._burst_frames = burst_frames
        self._burst_interval_ms = burst_interval_ms
        self._burst_timeout_seconds = burst_timeout_seconds
        self._freshness_seconds = freshness_seconds
        self._locator = locator
        self._relocator = relocator
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def source_kind(self) -> EnvironmentSourceKind:
        return EnvironmentSourceKind.WS2021_GAUGE

    def read(self, requested_at: datetime) -> EnvironmentReading:
        try:
            calibration = self._calibration_store.current()
        except CalibrationMissing:
            return self._unavailable(
                requested_at,
                ReadingFailureReason.CALIBRATION_MISSING,
                calibration_version="missing",
            )
        except CalibrationInvalid:
            return self._unavailable(
                requested_at,
                ReadingFailureReason.CALIBRATION_INVALID,
                calibration_version="invalid",
            )
        except Exception:
            return self._unavailable(
                requested_at,
                ReadingFailureReason.INTERNAL_ERROR,
                calibration_version="invalid",
            )

        try:
            burst = self._frame_source.capture_burst(
                frame_count=self._burst_frames,
                interval_ms=self._burst_interval_ms,
                timeout_seconds=self._burst_timeout_seconds,
            )
        except FrameSourceUnavailable:
            return self._unavailable(
                requested_at,
                ReadingFailureReason.FRAME_SOURCE_UNAVAILABLE,
                calibration_version=calibration.calibration_id,
            )
        except Exception:
            return self._unavailable(
                requested_at,
                ReadingFailureReason.INTERNAL_ERROR,
                calibration_version=calibration.calibration_id,
            )

        try:
            if self._locator is not None:
                if not burst.frames:
                    raise ValueError("gauge_not_found")
                first_frame = burst.frames[0]
                location = self._locator.locate(first_frame)
                calibration = self._relocator(calibration, location, first_frame)
            return self._reader.read(burst, calibration, self._now())
        except Exception:
            return self._unavailable(
                requested_at,
                (
                    ReadingFailureReason.CALIBRATION_INVALID
                    if self._locator is not None
                    else ReadingFailureReason.INTERNAL_ERROR
                ),
                calibration_version=calibration.calibration_id,
                sample_count=len(burst.frames),
            )

    def _unavailable(
        self,
        captured_at: datetime,
        reason: ReadingFailureReason,
        *,
        calibration_version: str,
        sample_count: int = 0,
    ) -> EnvironmentReading:
        return EnvironmentReading.unavailable(
            reading_id=str(uuid4()),
            source_kind=self.source_kind,
            captured_at=captured_at,
            failure_reason=reason,
            calibration_version=calibration_version,
            sample_count=sample_count,
            freshness_seconds=self._freshness_seconds,
        )
