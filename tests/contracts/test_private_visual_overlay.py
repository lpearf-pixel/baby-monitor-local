from __future__ import annotations

import importlib
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError


def contracts():
    return importlib.import_module("packages.contracts.private_visual_overlay")


def private_asset() -> dict[str, object]:
    return {
        "private_asset_id": "plc-0123456789abcdef0123456789abcdef",
        "sha256": "1" * 64,
        "bytes": 1_048_576,
        "duration_ms": 25_000,
        "codec": "hevc",
        "width": 2560,
        "height": 1440,
        "fps": 10.0,
        "scenario_ids": ["WIDE-02", "NEG-01"],
        "authorization_review": "pending",
        "privacy_review": "pending",
    }


def private_descriptor() -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_type": "PRIVATE_LOCAL_CAPTURE",
        "assets": [private_asset()],
    }


def test_private_descriptor_accepts_only_the_closed_metadata_shape() -> None:
    module = contracts()

    parsed = module.PrivateOverlayDescriptor.model_validate(private_descriptor())

    assert parsed.source_type is module.PrivateSourceType.PRIVATE_LOCAL_CAPTURE
    assert parsed.assets[0].scenario_ids == (
        module.ScenarioId.WIDE_02,
        module.ScenarioId.NEG_01,
    )
    assert set(parsed.assets[0].model_dump(mode="json")) == {
        "private_asset_id",
        "sha256",
        "bytes",
        "duration_ms",
        "codec",
        "width",
        "height",
        "fps",
        "scenario_ids",
        "authorization_review",
        "privacy_review",
    }


@pytest.mark.parametrize(
    "source_type",
    [
        "REAL",
        "PUBLIC_DATASET",
        "SYNTHETIC",
        "DIRECT_HTTPS",
        "MANUAL",
        "APPLICATION_ONLY",
        "NOT_AVAILABLE",
    ],
)
def test_private_descriptor_rejects_every_public_source_or_download_type(
    source_type: str,
) -> None:
    module = contracts()
    payload = private_descriptor()
    payload["source_type"] = source_type

    with pytest.raises(ValidationError):
        module.PrivateOverlayDescriptor.model_validate(payload)


@pytest.mark.parametrize(
    "forbidden",
    [
        {"source_url": "https://example.invalid/a.mp4"},
        {"file_url": "file:///private/a.mp4"},
        {"path": "assets/a.mp4"},
        {"absolute_path": "/private/a.mp4"},
        {"host": "localhost"},
        {"ip": "192.0.2.1"},
        {"camera_uri": "rtsp://example.invalid/source"},
    ],
)
def test_private_asset_rejects_locator_fields(forbidden: dict[str, str]) -> None:
    module = contracts()
    payload = private_descriptor()
    payload["assets"][0].update(forbidden)  # type: ignore[index,union-attr]

    with pytest.raises(ValidationError):
        module.PrivateOverlayDescriptor.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("private_asset_id", "plc-room-wide"),
        ("private_asset_id", "plc-" + "A" * 32),
        ("sha256", "A" * 64),
        ("sha256", "1" * 63),
        ("bytes", 0),
        ("bytes", 128 * 1024 * 1024 + 1),
        ("duration_ms", 9_999),
        ("duration_ms", 60_001),
        ("codec", "opus"),
        ("width", 0),
        ("height", 0),
        ("fps", 0),
        ("fps", math.inf),
        ("scenario_ids", ["UNKNOWN-01"]),
        ("authorization_review", "unknown"),
        ("privacy_review", "reviewed"),
    ],
)
def test_private_asset_rejects_out_of_contract_metadata(
    field: str,
    value: object,
) -> None:
    module = contracts()
    payload = private_descriptor()
    payload["assets"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        module.PrivateOverlayDescriptor.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("bytes", True),
        ("bytes", "1048576"),
        ("duration_ms", True),
        ("duration_ms", "25000"),
        ("width", True),
        ("width", "2560"),
        ("height", True),
        ("height", "1440"),
        ("fps", True),
        ("fps", "10.0"),
    ],
)
def test_private_asset_rejects_coerced_numeric_metadata(
    field: str,
    value: object,
) -> None:
    module = contracts()
    payload = private_descriptor()
    payload["assets"][0][field] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        module.PrivateOverlayDescriptor.model_validate(payload)


def test_private_asset_rejects_duplicate_scenarios() -> None:
    module = contracts()
    payload = private_descriptor()
    payload["assets"][0]["scenario_ids"] = ["WIDE-02", "WIDE-02"]  # type: ignore[index]

    with pytest.raises(ValidationError, match="scenario_ids"):
        module.PrivateOverlayDescriptor.model_validate(payload)


@pytest.mark.parametrize("duplicate_field", ["private_asset_id", "sha256"])
def test_private_descriptor_rejects_duplicate_asset_identity(
    duplicate_field: str,
) -> None:
    module = contracts()
    payload = private_descriptor()
    second = private_asset()
    second["private_asset_id"] = "plc-fedcba9876543210fedcba9876543210"
    second["sha256"] = "2" * 64
    second[duplicate_field] = payload["assets"][0][duplicate_field]  # type: ignore[index]
    payload["assets"].append(second)  # type: ignore[union-attr]

    with pytest.raises(ValidationError):
        module.PrivateOverlayDescriptor.model_validate(payload)


def test_private_descriptor_canonical_bytes_are_stable() -> None:
    module = contracts()
    parsed = module.PrivateOverlayDescriptor.model_validate(private_descriptor())

    first = module.canonical_private_overlay_bytes(parsed)
    second = module.canonical_private_overlay_bytes(
        module.PrivateOverlayDescriptor.model_validate(
            json.loads(json.dumps(private_descriptor(), sort_keys=True))
        )
    )

    assert first == second
    assert first.endswith(b"}")
    assert b"source_url" not in first


def test_private_descriptor_loader_redacts_invalid_locator(
    tmp_path: Path,
) -> None:
    module = contracts()
    payload = private_descriptor()
    payload["assets"][0]["source_url"] = "https://secret.invalid/private.mp4"  # type: ignore[index]
    descriptor = tmp_path / "household-name.json"
    descriptor.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        module.PrivateVisualOverlayError,
        match="^private_overlay_forbidden_locator$",
    ) as failure:
        module.load_private_overlay_descriptor(descriptor)

    assert "household-name" not in str(failure.value)
    assert "secret" not in str(failure.value)


def test_private_descriptor_loader_redacts_malformed_input(tmp_path: Path) -> None:
    module = contracts()
    descriptor = tmp_path / "household-name.json"
    descriptor.write_text("{", encoding="utf-8")

    with pytest.raises(
        module.PrivateVisualOverlayError,
        match="^private_overlay_metadata_invalid$",
    ) as failure:
        module.load_private_overlay_descriptor(descriptor)

    assert "household-name" not in str(failure.value)


def test_synthetic_example_uses_the_same_closed_loader() -> None:
    module = contracts()

    parsed = module.load_private_overlay_descriptor(
        Path("config/private_visual_overlay.example.json")
    )

    assert parsed.assets[0].authorization_review is module.PrivateReviewState.PENDING
    assert parsed.assets[0].privacy_review is module.PrivateReviewState.PENDING
