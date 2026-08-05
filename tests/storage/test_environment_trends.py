from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
from pathlib import Path

import pytest

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def storage_module():
    return importlib.import_module("services.storage.environment")


def available(
    reading_id: str,
    captured_at: datetime,
    temperature: float,
    humidity: float,
) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=temperature,
        humidity_rh=humidity,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def unavailable(reading_id: str, captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.unavailable(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        failure_reason=ReadingFailureReason.GLARE,
        calibration_version="calibration-1",
        sample_count=5,
    )


def test_24_hour_trend_uses_five_minute_buckets_and_literal_statistics(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    window_start = NOW - timedelta(hours=24)
    store.append(available("a", window_start + timedelta(minutes=1), 20, 40))
    store.append(unavailable("b", window_start + timedelta(minutes=2)))
    store.append(available("c", window_start + timedelta(minutes=4), 24, 50))

    trend = store.trend(module.TrendWindow.HOURS_24, now=NOW)

    assert len(trend.buckets) == 288
    first = trend.buckets[0]
    assert first.sample_count == 3
    assert first.available_count == 2
    assert first.availability_rate == pytest.approx(2 / 3)
    assert (first.temperature_min, first.temperature_median, first.temperature_max) == (
        20,
        22,
        24,
    )
    assert (first.humidity_min, first.humidity_median, first.humidity_max) == (
        40,
        45,
        50,
    )
    gap = trend.buckets[1]
    assert gap.sample_count == 0
    assert gap.temperature_median is None
    assert gap.humidity_median is None


def test_7_day_trend_uses_one_hour_buckets(tmp_path: Path) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    window_start = NOW - timedelta(days=7)
    store.append(available("a", window_start + timedelta(minutes=30), 21, 47))

    trend = store.trend(module.TrendWindow.DAYS_7, now=NOW)

    assert len(trend.buckets) == 168
    assert trend.bucket_seconds == 3600
    assert trend.buckets[0].temperature_median == 21
    assert trend.buckets[1].temperature_median is None


def test_trend_rejects_arbitrary_window_strings(tmp_path: Path) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")

    with pytest.raises(ValueError, match="closed TrendWindow"):
        store.trend("365d", now=NOW)
