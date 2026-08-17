from __future__ import annotations

from datetime import UTC, datetime
import importlib

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
    ReadingState,
)
from services.gauge.calibration import CalibrationInvalid, CalibrationMissing
from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation, GaugeLocalizationCode, GaugeLocalizationError
from services.stream.frame_source import CapturedFrame, FrameBurst, FrameSourceUnavailable
from tests.gauge.synthetic_dial import calibration


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def source_module():
    return importlib.import_module("services.gauge.source")


class FailIfCalled:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected dependency access: {name}")


class EmptyStore:
    def current(self) -> object:
        raise CalibrationMissing("private path omitted")


class InvalidStore:
    def current(self) -> object:
        raise CalibrationInvalid("private path omitted")


class CalibrationStore:
    def current(self):
        return calibration()


class BrokenFrameSource:
    def capture_burst(self, **kwargs: object) -> FrameBurst:
        raise FrameSourceUnavailable("malformed_mjpeg")


class RecordingFrameSource:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    def capture_burst(self, **kwargs: object) -> FrameBurst:
        self.kwargs = kwargs
        return FrameBurst(frames=())


class RecordingReader:
    def __init__(self) -> None:
        self.calls: list[tuple[FrameBurst, object, datetime]] = []

    def read(
        self,
        frame_burst: FrameBurst,
        current_calibration: object,
        requested_at: datetime,
    ) -> EnvironmentReading:
        self.calls.append((frame_burst, current_calibration, requested_at))
        return EnvironmentReading.unavailable(
            reading_id="reader-result",
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=requested_at,
            failure_reason=ReadingFailureReason.INSUFFICIENT_VALID_FRAMES,
            calibration_version="synthetic-calibration-v2",
            sample_count=0,
        )


class BurstFrameSource:
    def __init__(self) -> None:
        self.frames = tuple(
            CapturedFrame(b"synthetic", NOW, 2560, 1440) for _ in range(5)
        )

    def capture_burst(self, **kwargs: object) -> FrameBurst:
        return FrameBurst(frames=self.frames)


def test_missing_calibration_publishes_unavailable_without_opening_frames() -> None:
    module = source_module()
    source = module.Ws2021GaugeSource(
        frame_source=FailIfCalled(),
        calibration_store=EmptyStore(),
        reader=FailIfCalled(),
    )

    reading = source.read(NOW)

    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_MISSING
    assert reading.calibration_version == "missing"
    assert reading.temperature_c is None
    assert reading.humidity_rh is None


def test_invalid_calibration_publishes_stable_unavailable() -> None:
    module = source_module()
    source = module.Ws2021GaugeSource(
        frame_source=FailIfCalled(),
        calibration_store=InvalidStore(),
        reader=FailIfCalled(),
    )

    reading = source.read(NOW)

    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID
    assert reading.calibration_version == "invalid"
    assert "private" not in reading.model_dump_json()


def test_frame_failure_is_redacted_and_keeps_current_calibration_version() -> None:
    module = source_module()
    source = module.Ws2021GaugeSource(
        frame_source=BrokenFrameSource(),
        calibration_store=CalibrationStore(),
        reader=FailIfCalled(),
    )

    reading = source.read(NOW)

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.FRAME_SOURCE_UNAVAILABLE
    assert reading.calibration_version == "synthetic-calibration-v2"
    assert "malformed_mjpeg" not in reading.model_dump_json()


def test_source_uses_fixed_burst_settings_and_delegates_to_reader() -> None:
    module = source_module()
    frames = RecordingFrameSource()
    reader = RecordingReader()
    source = module.Ws2021GaugeSource(
        frame_source=frames,
        calibration_store=CalibrationStore(),
        reader=reader,
        burst_frames=5,
        burst_interval_ms=500,
        burst_timeout_seconds=8,
        now=lambda: NOW,
    )

    reading = source.read(NOW)

    assert source.source_kind is EnvironmentSourceKind.WS2021_GAUGE
    assert frames.kwargs == {
        "frame_count": 5,
        "interval_ms": 500,
        "timeout_seconds": 8,
    }
    assert len(reader.calls) == 1
    assert reader.calls[0][2] == NOW
    assert reading.reading_id == "reader-result"


def test_source_passes_algorithm_entry_time_after_capture() -> None:
    frames = RecordingFrameSource()
    reader = RecordingReader()
    processing_time = datetime(2026, 8, 5, 12, 0, 6, tzinfo=UTC)
    source = source_module().Ws2021GaugeSource(
        frame_source=frames,
        calibration_store=CalibrationStore(),
        reader=reader,
        now=lambda: processing_time,
    )

    source.read(NOW)

    assert reader.calls[0][2] == processing_time


def test_unexpected_reader_error_becomes_internal_error_without_details() -> None:
    module = source_module()

    class BrokenReader:
        def read(self, *args: object, **kwargs: object) -> EnvironmentReading:
            raise RuntimeError("Ollama token at /private/family")

    source = module.Ws2021GaugeSource(
        frame_source=RecordingFrameSource(),
        calibration_store=CalibrationStore(),
        reader=BrokenReader(),
    )

    reading = source.read(NOW)

    assert reading.failure_reason is ReadingFailureReason.INTERNAL_ERROR
    assert "/private" not in reading.model_dump_json()
    assert "Ollama" not in reading.model_dump_json()


def test_auto_localization_runs_once_and_reuses_migrated_geometry_for_burst() -> None:
    frames = BurstFrameSource()
    reader = RecordingReader()
    located = GaugeLocation(
        box=NormalizedRect(x=0.4, y=0.1, width=0.2, height=0.5),
        confidence=0.9,
        model_version="test-v1",
    )

    class Locator:
        def __init__(self) -> None:
            self.calls: list[CapturedFrame] = []

        def locate(self, frame: CapturedFrame) -> GaugeLocation:
            self.calls.append(frame)
            return located

    locator = Locator()
    migrated = calibration().model_copy(update={"center_x": 0.6})
    relocations: list[tuple[object, GaugeLocation, CapturedFrame]] = []

    def relocate(current: object, location: GaugeLocation, frame: CapturedFrame):
        relocations.append((current, location, frame))
        return migrated

    source = source_module().Ws2021GaugeSource(
        frame_source=frames,
        calibration_store=CalibrationStore(),
        reader=reader,
        locator=locator,
        relocator=relocate,
        now=lambda: NOW,
    )

    source.read(NOW)

    assert locator.calls == [frames.frames[0]]
    assert relocations[0][1:] == (located, frames.frames[0])
    assert reader.calls[0][1] is migrated
    assert reader.calls[0][0].frames == frames.frames


def test_fixed_roi_stabilization_overrides_model_locator_for_burst() -> None:
    frames = BurstFrameSource()
    reader = RecordingReader()
    located = GaugeLocation(
        box=NormalizedRect(x=0.6, y=0.2, width=0.35, height=0.7),
        confidence=1.0,
        model_version="fixed-roi-v1",
    )

    class StableFixedRoi:
        def __init__(self) -> None:
            self.calls: list[CapturedFrame] = []

        def observe(self, frame: CapturedFrame) -> GaugeLocation | None:
            self.calls.append(frame)
            if len(self.calls) < 3:
                return None
            return located

    stable = StableFixedRoi()
    migrated = calibration().model_copy(update={"center_x": 0.7})
    relocations: list[tuple[object, GaugeLocation, CapturedFrame]] = []

    def relocate(current: object, location: GaugeLocation, frame: CapturedFrame):
        relocations.append((current, location, frame))
        return migrated

    source = source_module().Ws2021GaugeSource(
        frame_source=frames,
        calibration_store=CalibrationStore(),
        reader=reader,
        fixed_roi_factory=lambda current: stable,
        locator=FailIfCalled(),
        relocator=relocate,
        now=lambda: NOW,
    )

    source.read(NOW)

    assert stable.calls == list(frames.frames[:3])
    assert relocations == [(calibration(), located, frames.frames[2])]
    assert reader.calls[0][1] is migrated


def test_unstable_fixed_roi_returns_unavailable_without_reader_or_model() -> None:
    class UnstableFixedRoi:
        def observe(self, frame: CapturedFrame) -> GaugeLocation | None:
            return None

    source = source_module().Ws2021GaugeSource(
        frame_source=BurstFrameSource(),
        calibration_store=CalibrationStore(),
        reader=FailIfCalled(),
        fixed_roi_factory=lambda current: UnstableFixedRoi(),
        locator=FailIfCalled(),
        relocator=FailIfCalled(),
    )

    reading = source.read(NOW)

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID
    assert reading.sample_count == 5
    assert "fixed_roi" not in reading.model_dump_json()


def test_model_locator_fallback_is_unchanged_when_fixed_roi_disabled() -> None:
    frames = BurstFrameSource()
    reader = RecordingReader()
    located = GaugeLocation(
        box=NormalizedRect(x=0.4, y=0.1, width=0.2, height=0.5),
        confidence=0.9,
        model_version="test-v1",
    )

    class Locator:
        def __init__(self) -> None:
            self.calls: list[CapturedFrame] = []

        def locate(self, frame: CapturedFrame) -> GaugeLocation:
            self.calls.append(frame)
            return located

    locator = Locator()
    migrated = calibration().model_copy(update={"center_x": 0.6})

    source = source_module().Ws2021GaugeSource(
        frame_source=frames,
        calibration_store=CalibrationStore(),
        reader=reader,
        fixed_roi_factory=lambda current: None,
        locator=locator,
        relocator=lambda current, location, frame: migrated,
        now=lambda: NOW,
    )

    source.read(NOW)

    assert locator.calls == [frames.frames[0]]
    assert reader.calls[0][1] is migrated


def test_auto_localization_failure_never_calls_reader_or_reuses_geometry() -> None:
    class MissingLocator:
        def locate(self, frame: CapturedFrame) -> GaugeLocation:
            raise GaugeLocalizationError(GaugeLocalizationCode.NOT_FOUND)

    source = source_module().Ws2021GaugeSource(
        frame_source=BurstFrameSource(),
        calibration_store=CalibrationStore(),
        reader=FailIfCalled(),
        locator=MissingLocator(),
        relocator=FailIfCalled(),
    )

    reading = source.read(NOW)

    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID
    assert reading.sample_count == 5
