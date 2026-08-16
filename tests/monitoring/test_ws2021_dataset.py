from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation
from services.stream.frame_source import CapturedFrame


def _frame(*, textured: bool = True) -> CapturedFrame:
    image = np.full((300, 500, 3), 220, dtype=np.uint8)
    if textured:
        for offset in range(0, 300, 12):
            cv2.line(image, (0, offset), (499, offset), (20, 20, 20), 2)
        cv2.circle(image, (250, 150), 55, (0, 0, 0), 4)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return CapturedFrame(
        jpeg=encoded.tobytes(),
        captured_at=datetime(2026, 8, 16, tzinfo=UTC),
        width=500,
        height=300,
    )


def _location() -> GaugeLocation:
    return GaugeLocation(
        box=NormalizedRect(x=0.3, y=0.15, width=0.4, height=0.7),
        confidence=0.9,
        model_version="test-v1",
    )


class PrivacyGuard:
    def __init__(self, overlaps: bool = False, fails: bool = False) -> None:
        self.overlap_value = overlaps
        self.fails = fails

    def overlaps(self, image: np.ndarray, box: NormalizedRect) -> bool:  # type: ignore[no-redef]
        if self.fails:
            raise RuntimeError("private backend detail")
        assert image.shape == (300, 500, 3)
        assert box == _location().box
        return self.overlap_value


class RecordingStore:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def save(self, crop_jpeg: bytes) -> bool:
        self.payloads.append(crop_jpeg)
        return True


class DuplicateStore(RecordingStore):
    def save(self, crop_jpeg: bytes) -> bool:
        self.payloads.append(crop_jpeg)
        return False


def test_collector_persists_only_the_bounded_crop() -> None:
    from packages.monitoring.ws2021_dataset import CollectionCode, Ws2021Collector

    store = RecordingStore()
    result = Ws2021Collector(store=store, privacy_guard=PrivacyGuard()).collect(
        _frame(), _location()
    )

    assert result is CollectionCode.ACCEPTED
    assert len(store.payloads) == 1
    with Image.open(BytesIO(store.payloads[0])) as crop:
        assert crop.size == (200, 210)
    assert store.payloads[0] != _frame().jpeg


def test_collector_fails_closed_for_privacy_overlap_or_guard_failure() -> None:
    from packages.monitoring.ws2021_dataset import CollectionCode, Ws2021Collector

    for guard in (PrivacyGuard(overlaps=True), PrivacyGuard(fails=True)):
        store = RecordingStore()
        result = Ws2021Collector(store=store, privacy_guard=guard).collect(
            _frame(), _location()
        )
        assert result is CollectionCode.PRIVACY_REJECTED
        assert store.payloads == []


def test_collector_rejects_low_quality_crop_before_persistence() -> None:
    from packages.monitoring.ws2021_dataset import CollectionCode, Ws2021Collector

    store = RecordingStore()
    result = Ws2021Collector(store=store, privacy_guard=PrivacyGuard()).collect(
        _frame(textured=False), _location()
    )
    assert result is CollectionCode.QUALITY_REJECTED
    assert store.payloads == []


def test_collector_reports_store_duplicate_without_exposing_identity() -> None:
    from packages.monitoring.ws2021_dataset import CollectionCode, Ws2021Collector

    store = DuplicateStore()
    result = Ws2021Collector(store=store, privacy_guard=PrivacyGuard()).collect(
        _frame(), _location()
    )
    assert result is CollectionCode.DUPLICATE_REJECTED
    assert len(store.payloads) == 1


def test_candidate_privacy_guard_rejects_person_or_skin_overlap() -> None:
    from packages.monitoring.ws2021_dataset import (
        CandidatePrivacyGuard,
        PrivacyCandidates,
    )

    class Backend:
        def __init__(self, candidates: PrivacyCandidates) -> None:
            self.candidates = candidates

        def detect(self, image: np.ndarray) -> PrivacyCandidates:
            return self.candidates

    far = NormalizedRect(x=0.01, y=0.01, width=0.1, height=0.1)
    overlap = NormalizedRect(x=0.2, y=0.2, width=0.2, height=0.2)
    image = np.zeros((300, 500, 3), dtype=np.uint8)

    assert not CandidatePrivacyGuard(
        backend=Backend(PrivacyCandidates(person_boxes=(far,)))
    ).overlaps(image, _location().box)
    assert CandidatePrivacyGuard(
        backend=Backend(PrivacyCandidates(person_boxes=(overlap,)))
    ).overlaps(image, _location().box)
    assert CandidatePrivacyGuard(
        backend=Backend(PrivacyCandidates(skin_boxes=(overlap,)))
    ).overlaps(image, _location().box)


def test_private_store_is_atomic_private_and_deduplicates(tmp_path: Path) -> None:
    from packages.monitoring.ws2021_dataset import PrivateCropStore

    root = tmp_path / "ws2021"
    store = PrivateCropStore(root)
    crop = RecordingStore()
    from packages.monitoring.ws2021_dataset import Ws2021Collector

    assert Ws2021Collector(store=crop, privacy_guard=PrivacyGuard()).collect(
        _frame(), _location()
    ).value == "accepted"
    payload = crop.payloads[0]

    assert store.save(payload) is True
    assert store.save(payload) is False
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    images = list(root.glob("*.jpg"))
    metadata = list(root.glob("*.json"))
    assert len(images) == len(metadata) == 1
    assert stat.S_IMODE(images[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(metadata[0].stat().st_mode) == 0o600
    assert not list(root.glob("*.partial"))
    record = json.loads(metadata[0].read_text(encoding="utf-8"))
    assert set(record) == {"class_name", "height", "sha256", "width"}
    assert record["class_name"] == "ws2021"
    assert "/" not in images[0].name


def test_collection_counts_expose_only_closed_aggregate_fields() -> None:
    from packages.monitoring.ws2021_dataset import CollectionCode, CollectionCounts

    counts = CollectionCounts()
    for code in (
        CollectionCode.ACCEPTED,
        CollectionCode.PRIVACY_REJECTED,
        CollectionCode.DUPLICATE_REJECTED,
        CollectionCode.QUALITY_REJECTED,
        CollectionCode.FAILED,
    ):
        counts = counts.record(code)

    assert counts.model_dump() == {
        "accepted": 1,
        "privacy_rejected": 1,
        "duplicate_rejected": 1,
        "quality_rejected": 1,
        "failed": 1,
    }
