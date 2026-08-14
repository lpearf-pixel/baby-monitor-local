from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path

from PIL import Image
import pytest

from packages.contracts.vision import VisualRiskKind
from services.events.guardian_query import GuardianEventQueryService
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.evidence_files import GuardianEvidenceFiles
from services.vision.evidence_retention import (
    EvidenceRetentionReport,
    GuardianEvidenceRetention,
    GuardianEvidenceRetentionWorker,
)
from services.vision.frame_policy import PreparedAnalysisFrame


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def safe_frame(captured_at: datetime, color: tuple[int, int, int]) -> PreparedAnalysisFrame:
    output = BytesIO()
    Image.new("RGB", (32, 18), color).save(output, format="JPEG", quality=80)
    return PreparedAnalysisFrame(
        jpeg=output.getvalue(),
        captured_at=captured_at,
        width=32,
        height=18,
        crop_box=(0, 0, 32, 18),
    )


def ready_recovered_event(
    store: VisualRiskEventStore,
    files: GuardianEvidenceFiles,
    *,
    event_id: str,
    opened_at: datetime,
    completed_at: datetime,
    recovered_at: datetime,
    color: tuple[int, int, int],
    recovery_notification_state: str = "delivered",
) -> None:
    store.open_event(
        event_id=event_id,
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=opened_at,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    frame = safe_frame(opened_at, color)
    snapshot_key = files.write_snapshot(event_id, frame)
    store.begin_evidence(
        event_id=event_id,
        started_at=opened_at,
        capture_deadline=opened_at + timedelta(seconds=30),
        snapshot_key=snapshot_key,
        frame_count=1,
    )
    store.recover_event(
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        recovered_at=recovered_at,
        confidence=0.91,
        rule_version="visual-risk-v1",
    )
    notification = store.queue_notification(
        notification_id=f"retention-{event_id}",
        event_id=event_id,
        stage="risk_recovered",
        queued_at=recovered_at,
    )
    if recovery_notification_state == "delivered":
        store.record_notification_result(
            notification_id=notification.notification_id,
            attempted_at=recovered_at + timedelta(microseconds=1),
            result_code="ok",
        )
    clip_key = files.write_clip(event_id, (frame,))
    store.complete_evidence(
        event_id=event_id,
        completed_at=completed_at,
        clip_key=clip_key,
        frame_count=1,
    )


def test_age_cleanup_uses_later_terminal_time_and_keeps_event_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store = VisualRiskEventStore(database)
    store.migrate()
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    cutoff = NOW - timedelta(days=30)
    ready_recovered_event(
        store,
        files,
        event_id="expired-at-boundary",
        opened_at=cutoff - timedelta(minutes=1),
        completed_at=cutoff - timedelta(seconds=1),
        recovered_at=cutoff,
        color=(255, 0, 0),
    )
    ready_recovered_event(
        store,
        files,
        event_id="young-by-evidence",
        opened_at=cutoff - timedelta(minutes=1),
        completed_at=cutoff + timedelta(microseconds=1),
        recovered_at=cutoff,
        color=(0, 255, 0),
    )

    report = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=1_000_000,
    ).cleanup(NOW)

    assert report.result == "deleted"
    assert report.deleted_count == 1
    assert report.reclaimed_bytes > 0
    assert store.get_event("expired-at-boundary") is not None
    assert store.get_evidence("expired-at-boundary") is None
    assert store.get_evidence("young-by-evidence") is not None
    projected = GuardianEventQueryService(database).recent_events()
    projected_by_id = {event.event_id: event for event in projected.events}
    assert projected_by_id["expired-at-boundary"].evidence_state == "unavailable"
    assert projected_by_id["young-by-evidence"].evidence_state == "ready"


def test_age_and_quota_cleanup_protect_open_collecting_and_pending_notification(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    old = NOW - timedelta(days=90)
    ready_recovered_event(
        store,
        files,
        event_id="pending-old",
        opened_at=old,
        completed_at=old + timedelta(seconds=30),
        recovered_at=old + timedelta(seconds=40),
        color=(255, 0, 0),
        recovery_notification_state="pending",
    )
    store.open_event(
        event_id="open-collecting",
        risk_kind=VisualRiskKind.PRONE_CANDIDATE,
        opened_at=old,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    frame = safe_frame(old, (0, 255, 0))
    snapshot_key = files.write_snapshot("open-collecting", frame)
    store.begin_evidence(
        event_id="open-collecting",
        started_at=old,
        capture_deadline=old + timedelta(seconds=30),
        snapshot_key=snapshot_key,
        frame_count=1,
    )

    report = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=1,
    ).cleanup(NOW)

    assert report.result == "quota_unmet"
    assert report.deleted_count == 0
    assert store.get_evidence("pending-old") is not None
    assert store.get_evidence("open-collecting") is not None
    assert files.event_bytes("pending-old") > 0
    assert files.event_bytes("open-collecting") > 0


def test_quota_cleanup_removes_oldest_eligible_evidence_first(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    for index, event_id in enumerate(("oldest", "middle", "newest")):
        opened_at = NOW - timedelta(days=3 - index)
        ready_recovered_event(
            store,
            files,
            event_id=event_id,
            opened_at=opened_at,
            completed_at=opened_at + timedelta(seconds=30),
            recovered_at=opened_at + timedelta(seconds=40),
            color=(10 + index, 20 + index, 30 + index),
        )
    initial_usage = files.total_bytes()
    oldest_bytes = files.event_bytes("oldest")

    report = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=initial_usage - oldest_bytes,
    ).cleanup(NOW)

    assert report.result == "deleted"
    assert report.deleted_count == 1
    assert report.reclaimed_bytes == oldest_bytes
    assert report.usage_bytes == initial_usage - oldest_bytes
    assert store.get_evidence("oldest") is None
    assert store.get_evidence("middle") is not None
    assert store.get_evidence("newest") is not None


def test_unmanaged_usage_reports_quota_unmet_after_eligible_cleanup(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    root = tmp_path / "guardian-evidence"
    files = GuardianEvidenceFiles(root)
    opened_at = NOW - timedelta(days=1)
    ready_recovered_event(
        store,
        files,
        event_id="managed",
        opened_at=opened_at,
        completed_at=opened_at + timedelta(seconds=30),
        recovered_at=opened_at + timedelta(seconds=40),
        color=(1, 2, 3),
    )
    unmanaged = root / "unmanaged.bin"
    unmanaged.write_bytes(b"unmanaged-private")

    report = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=len(b"unmanaged-private") - 1,
    ).cleanup(NOW)

    assert report.result == "quota_unmet"
    assert report.deleted_count == 1
    assert report.usage_bytes == len(b"unmanaged-private")
    assert unmanaged.read_bytes() == b"unmanaged-private"
    assert store.get_evidence("managed") is None


def test_filesystem_failure_preserves_database_evidence_for_retry(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    root = tmp_path / "guardian-evidence"
    files = GuardianEvidenceFiles(root)
    opened_at = NOW - timedelta(days=90)
    ready_recovered_event(
        store,
        files,
        event_id="unsafe-event",
        opened_at=opened_at,
        completed_at=opened_at + timedelta(seconds=30),
        recovered_at=opened_at + timedelta(seconds=40),
        color=(1, 2, 3),
    )
    digest = hashlib.sha256(b"unsafe-event").hexdigest()
    unexpected = root / "visual-risk" / digest / "unexpected.txt"
    unexpected.write_text("private", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe evidence entry"):
        GuardianEvidenceRetention(
            store=store,
            files=files,
            retention_days=30,
            quota_bytes=1_000_000,
        ).cleanup(NOW)

    evidence = store.get_evidence("unsafe-event")
    assert evidence is not None
    assert evidence.snapshot_key is not None
    assert (root / evidence.snapshot_key).is_file()
    assert unexpected.is_file()


def test_database_guard_failure_leaves_retryable_row_and_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    opened_at = NOW - timedelta(days=90)
    ready_recovered_event(
        store,
        files,
        event_id="retry-event",
        opened_at=opened_at,
        completed_at=opened_at + timedelta(seconds=30),
        recovered_at=opened_at + timedelta(seconds=40),
        color=(1, 2, 3),
    )
    original_delete = store.delete_evidence_if_eligible
    monkeypatch.setattr(
        store,
        "delete_evidence_if_eligible",
        lambda _entry, _delete_files: None,
    )
    retention = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=1_000_000,
    )

    with pytest.raises(RuntimeError, match="eligibility changed"):
        retention.cleanup(NOW)

    assert files.event_bytes("retry-event") > 0
    assert store.get_evidence("retry-event") is not None
    monkeypatch.setattr(store, "delete_evidence_if_eligible", original_delete)
    report = retention.cleanup(NOW)
    assert report.result == "deleted"
    assert report.reclaimed_bytes > 0
    assert store.get_evidence("retry-event") is None


def test_retention_rejects_naive_time_and_nonpositive_limits(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")

    with pytest.raises(ValueError, match="retention_days"):
        GuardianEvidenceRetention(
            store=store,
            files=files,
            retention_days=0,
            quota_bytes=1,
        )
    with pytest.raises(ValueError, match="quota_bytes"):
        GuardianEvidenceRetention(
            store=store,
            files=files,
            retention_days=30,
            quota_bytes=0,
        )
    retention = GuardianEvidenceRetention(
        store=store,
        files=files,
        retention_days=30,
        quota_bytes=1,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        retention.cleanup(datetime(2026, 9, 15, 12, 0))


class ScriptedStopEvent:
    def __init__(self, wait_results: list[bool], *, initially_set: bool = False) -> None:
        self._wait_results = list(wait_results)
        self._set = initially_set
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        result = self._wait_results.pop(0)
        if result:
            self._set = True
        return result


def test_retention_worker_runs_immediately_then_waits_one_day() -> None:
    reports = [
        EvidenceRetentionReport(
            result="deleted",
            deleted_count=2,
            reclaimed_bytes=300,
            usage_bytes=700,
            quota_bytes=1_000,
        ),
        EvidenceRetentionReport(
            result="within_quota",
            deleted_count=0,
            reclaimed_bytes=0,
            usage_bytes=700,
            quota_bytes=1_000,
        ),
    ]
    calls: list[datetime] = []
    stream = StringIO()
    stop_event = ScriptedStopEvent([False, True])

    GuardianEvidenceRetentionWorker(
        cleanup=lambda now: calls.append(now) or reports[len(calls) - 1],
        stream=stream,
        now=lambda: NOW,
    ).run(stop_event)

    assert calls == [NOW, NOW]
    assert stop_event.waits == [86_400, 86_400]
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines == [
        {
            "code": "guardian.evidence_retention_completed",
            "component": "baby_guardian",
            "deleted_count": 2,
            "observed_at": NOW.isoformat(),
            "quota_bytes": 1_000,
            "reclaimed_bytes": 300,
            "result": "deleted",
            "schema_version": 1,
            "usage_bytes": 700,
        },
        {
            "code": "guardian.evidence_retention_completed",
            "component": "baby_guardian",
            "deleted_count": 0,
            "observed_at": NOW.isoformat(),
            "quota_bytes": 1_000,
            "reclaimed_bytes": 0,
            "result": "within_quota",
            "schema_version": 1,
            "usage_bytes": 700,
        },
    ]


def test_retention_worker_redacts_failure_and_does_not_run_after_stop() -> None:
    stream = StringIO()
    failed_stop = ScriptedStopEvent([True])

    GuardianEvidenceRetentionWorker(
        cleanup=lambda _now: (_ for _ in ()).throw(
            RuntimeError("token at /private/guardian-evidence")
        ),
        stream=stream,
        now=lambda: NOW,
    ).run(failed_stop)

    assert failed_stop.waits == [86_400]
    assert json.loads(stream.getvalue()) == {
        "code": "guardian.evidence_retention_failed",
        "component": "baby_guardian",
        "observed_at": NOW.isoformat(),
        "result": "retention_unavailable",
        "schema_version": 1,
    }
    assert "token" not in stream.getvalue()
    assert "private" not in stream.getvalue()

    calls: list[datetime] = []
    already_stopped = ScriptedStopEvent([], initially_set=True)
    GuardianEvidenceRetentionWorker(
        cleanup=lambda now: calls.append(now) or None,
        stream=StringIO(),
        now=lambda: NOW,
    ).run(already_stopped)
    assert calls == []


def test_retention_worker_redacts_clock_and_wait_failures() -> None:
    clock_stream = StringIO()
    GuardianEvidenceRetentionWorker(
        cleanup=lambda _now: (_ for _ in ()).throw(AssertionError("not called")),
        stream=clock_stream,
        now=lambda: (_ for _ in ()).throw(
            RuntimeError("token at /private/clock")
        ),
    ).run(ScriptedStopEvent([]))
    clock_log = json.loads(clock_stream.getvalue())
    assert clock_log["code"] == "guardian.evidence_retention_failed"
    assert clock_log["result"] == "retention_unavailable"
    assert "token" not in clock_stream.getvalue()
    assert "private" not in clock_stream.getvalue()

    class FailingWaitStopEvent:
        def is_set(self) -> bool:
            return False

        def wait(self, _timeout: float) -> bool:
            raise RuntimeError("token at /private/scheduler")

    wait_stream = StringIO()
    GuardianEvidenceRetentionWorker(
        cleanup=lambda _now: EvidenceRetentionReport(
            result="within_quota",
            deleted_count=0,
            reclaimed_bytes=0,
            usage_bytes=0,
            quota_bytes=1,
        ),
        stream=wait_stream,
        now=lambda: NOW,
    ).run(FailingWaitStopEvent())
    wait_logs = [json.loads(line) for line in wait_stream.getvalue().splitlines()]
    assert [item["code"] for item in wait_logs] == [
        "guardian.evidence_retention_completed",
        "guardian.evidence_retention_failed",
    ]
    assert "token" not in wait_stream.getvalue()
    assert "private" not in wait_stream.getvalue()
