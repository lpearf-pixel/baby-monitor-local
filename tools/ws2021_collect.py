from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path

from packages.contracts.settings import AppSettings
from packages.monitoring.ws2021_dataset import (
    CollectionCode,
    CollectionCounts,
    PrivateCropStore,
    Ws2021Collector,
)
from services.gauge.calibration import GaugeCalibrationStore
from services.gauge.locator import GaugeLocation, GaugeLocator, OpenVinoGaugeBackend
from services.gauge.privacy import Ws2021PrivacyGuard
from services.stream.frame_source import Go2RtcControlledFrameSource
from services.vision.realtime_models import build_realtime_model_backend


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Collect private WS2021 crops")
    command.add_argument("mode", choices=("calibrated", "model"))
    command.add_argument("--settings", type=Path, default=Path("runtime/settings.yaml"))
    command.add_argument("--duration-seconds", type=int, default=30, choices=range(1, 31))
    command.add_argument("--interval-ms", type=int, default=500, choices=range(250, 2001))
    return command


def main() -> int:
    arguments = parser().parse_args()
    counts = CollectionCounts()
    try:
        settings = AppSettings.load(arguments.settings)
        data_root = _resolve(settings.app.data_dir)
        calibration = GaugeCalibrationStore(
            _resolve(settings.environment.calibration_path)
        ).current()
        realtime = build_realtime_model_backend(
            data_root / "models/openvino-2025.4.1"
        )
        if realtime is None:
            raise ValueError("ws2021_collection_failed")
        collector = Ws2021Collector(
            store=PrivateCropStore(data_root / "training/ws2021/crops"),
            privacy_guard=Ws2021PrivacyGuard(backend=realtime),
        )
        frame_source = Go2RtcControlledFrameSource(
            base_url=(
                f"http://{settings.stream.go2rtc_api_host}:"
                f"{settings.stream.go2rtc_api_port}"
            )
        )
        locator = _locator(arguments.mode, settings, calibration)
        def attempt() -> CollectionCode:
            try:
                burst = frame_source.capture_burst(
                    frame_count=1,
                    interval_ms=0,
                    timeout_seconds=8,
                )
                frame = burst.frames[0]
                location = locator.locate(frame)
                return collector.collect(frame, location)
            except Exception:
                return CollectionCode.FAILED

        counts = _collect_for_duration(
            attempt,
            duration_seconds=arguments.duration_seconds,
            interval_seconds=arguments.interval_ms / 1000,
        )
    except Exception:
        counts = counts.record(CollectionCode.FAILED)
    print("ws2021_collect=complete")
    for name, value in counts.model_dump().items():
        print(f"{name}_count={value}")
    return 0 if counts.accepted > 0 else 2


class FixedLocator:
    def __init__(self, location: GaugeLocation) -> None:
        self._location = location

    def locate(self, frame: object) -> GaugeLocation:
        return self._location


def _locator(mode: str, settings: AppSettings, calibration: object) -> object:
    if mode == "calibrated":
        return FixedLocator(
            GaugeLocation(
                box=calibration.gauge_rect,
                confidence=1,
                model_version="schema-v2-bootstrap",
            )
        )
    model_path = _resolve(settings.environment.localization_model_path)
    return GaugeLocator(
        backend=OpenVinoGaugeBackend(
            model_path=model_path,
            metadata_path=model_path.with_name("metadata.json"),
        )
    )


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _collect_for_duration(
    attempt: Callable[[], CollectionCode],
    *,
    duration_seconds: float,
    interval_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CollectionCounts:
    deadline = monotonic() + duration_seconds
    counts = CollectionCounts()
    first = True
    while first or monotonic() < deadline:
        first = False
        counts = counts.record(attempt())
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(interval_seconds, remaining))
    return counts


if __name__ == "__main__":
    raise SystemExit(main())
