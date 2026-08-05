from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def calibration_module():
    return importlib.import_module("services.gauge.calibration")


def test_store_round_trips_schema_v2_without_returning_paths(
    tmp_path: Path,
    calibration_data: dict[str, object],
    reference_jpeg: bytes,
) -> None:
    module = calibration_module()
    store = module.GaugeCalibrationStore(tmp_path / "ws2021-v1.json")

    saved = store.save(calibration_data, reference_jpeg)
    current = store.current()

    assert saved.calibration_id == "calibration-test-0001"
    assert current == saved
    assert "tmp_path" not in saved.model_dump_json()
    assert (tmp_path / "ws2021-reference.jpg").read_bytes() == reference_jpeg


def test_invalid_save_never_replaces_current_calibration(
    tmp_path: Path,
    calibration_data: dict[str, object],
    reference_jpeg: bytes,
) -> None:
    module = calibration_module()
    store = module.GaugeCalibrationStore(tmp_path / "ws2021-v1.json")
    store.save(calibration_data, reference_jpeg)
    original_json = (tmp_path / "ws2021-v1.json").read_bytes()
    invalid = dict(calibration_data)
    invalid["schema_version"] = 1

    with pytest.raises(module.CalibrationInvalid):
        store.save(invalid, reference_jpeg)

    assert (tmp_path / "ws2021-v1.json").read_bytes() == original_json
    assert store.current().calibration_id == "calibration-test-0001"


def test_store_rejects_non_jpeg_without_overwriting_current(
    tmp_path: Path,
    calibration_data: dict[str, object],
    reference_jpeg: bytes,
) -> None:
    module = calibration_module()
    store = module.GaugeCalibrationStore(tmp_path / "ws2021-v1.json")
    store.save(calibration_data, reference_jpeg)

    with pytest.raises(module.CalibrationInvalid, match="reference JPEG"):
        store.save(calibration_data, b"not-a-family-image")

    assert store.current().calibration_id == "calibration-test-0001"


def test_store_keeps_only_three_previous_json_and_jpeg_backups(
    tmp_path: Path,
    calibration_data: dict[str, object],
    reference_jpeg: bytes,
) -> None:
    module = calibration_module()
    store = module.GaugeCalibrationStore(tmp_path / "ws2021-v1.json")

    for index in range(5):
        version = dict(calibration_data)
        version["calibration_id"] = f"calibration-test-{index:04d}"
        store.save(version, reference_jpeg)

    backups = tmp_path / "backups"
    assert len(list(backups.glob("*.json"))) == 3
    assert len(list(backups.glob("*.jpg"))) == 3


def test_corrupt_or_missing_current_calibration_has_stable_error(
    tmp_path: Path,
) -> None:
    module = calibration_module()
    store = module.GaugeCalibrationStore(tmp_path / "ws2021-v1.json")

    with pytest.raises(module.CalibrationMissing):
        store.current()

    (tmp_path / "ws2021-v1.json").write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(module.CalibrationInvalid):
        store.current()
