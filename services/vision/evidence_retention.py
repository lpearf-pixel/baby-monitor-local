from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import json
import sys
from typing import Literal, Protocol, TextIO

from pydantic import BaseModel, ConfigDict, Field

from services.storage.visual_risk import StoredEvidenceRetentionEntry


RetentionResult = Literal["within_quota", "deleted", "quota_unmet"]
RETENTION_INTERVAL_SECONDS = 86_400


class EvidenceRetentionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: RetentionResult
    deleted_count: int = Field(ge=0)
    reclaimed_bytes: int = Field(ge=0)
    usage_bytes: int = Field(ge=0)
    quota_bytes: int = Field(gt=0)


class EvidenceRetentionStore(Protocol):
    def list_evidence_retention_entries(
        self,
    ) -> tuple[StoredEvidenceRetentionEntry, ...]: ...

    def delete_evidence_if_eligible(
        self,
        entry: StoredEvidenceRetentionEntry,
        delete_files: Callable[[], int],
    ) -> int | None: ...


class EvidenceRetentionFiles(Protocol):
    def total_bytes(self) -> int: ...

    def delete_event(self, event_id: str) -> int: ...


class GuardianEvidenceRetention:
    def __init__(
        self,
        *,
        store: EvidenceRetentionStore,
        files: EvidenceRetentionFiles,
        retention_days: int,
        quota_bytes: int,
    ) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        if quota_bytes <= 0:
            raise ValueError("quota_bytes must be positive")
        self._store = store
        self._files = files
        self._retention_days = retention_days
        self._quota_bytes = quota_bytes

    def cleanup(self, now: datetime) -> EvidenceRetentionReport:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        entries = tuple(
            sorted(
                self._store.list_evidence_retention_entries(),
                key=lambda entry: (entry.retention_at, entry.event_id),
            )
        )
        cutoff = now - timedelta(days=self._retention_days)
        deleted: set[str] = set()
        reclaimed_bytes = 0

        for entry in entries:
            if entry.deletable and entry.retention_at <= cutoff:
                reclaimed_bytes += self._delete(entry)
                deleted.add(entry.event_id)

        usage_bytes = self._files.total_bytes()
        for entry in entries:
            if usage_bytes <= self._quota_bytes:
                break
            if entry.deletable and entry.event_id not in deleted:
                reclaimed_bytes += self._delete(entry)
                deleted.add(entry.event_id)
                usage_bytes = self._files.total_bytes()

        usage_bytes = self._files.total_bytes()
        if usage_bytes > self._quota_bytes:
            result: RetentionResult = "quota_unmet"
        elif deleted:
            result = "deleted"
        else:
            result = "within_quota"
        return EvidenceRetentionReport(
            result=result,
            deleted_count=len(deleted),
            reclaimed_bytes=reclaimed_bytes,
            usage_bytes=usage_bytes,
            quota_bytes=self._quota_bytes,
        )

    def _delete(self, entry: StoredEvidenceRetentionEntry) -> int:
        reclaimed = self._store.delete_evidence_if_eligible(
            entry,
            lambda: self._files.delete_event(entry.event_id),
        )
        if reclaimed is None:
            raise RuntimeError("evidence retention eligibility changed")
        return reclaimed


class RetentionStopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class _RetentionLog:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def completed(
        self,
        *,
        observed_at: datetime,
        report: EvidenceRetentionReport,
    ) -> None:
        self._emit(
            {
                "schema_version": 1,
                "component": "baby_guardian",
                "code": "guardian.evidence_retention_completed",
                "observed_at": observed_at.isoformat(),
                **report.model_dump(),
            }
        )

    def failed(self, *, observed_at: datetime) -> None:
        self._emit(
            {
                "schema_version": 1,
                "component": "baby_guardian",
                "code": "guardian.evidence_retention_failed",
                "observed_at": observed_at.isoformat(),
                "result": "retention_unavailable",
            }
        )

    def _emit(self, payload: dict[str, object]) -> None:
        try:
            self._stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self._stream.flush()
        except Exception:
            return


class GuardianEvidenceRetentionWorker:
    def __init__(
        self,
        *,
        cleanup: Callable[[datetime], EvidenceRetentionReport],
        stream: TextIO = sys.stderr,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._cleanup = cleanup
        self._log = _RetentionLog(stream)
        self._now = now or (lambda: datetime.now().astimezone())

    def run(self, stop_event: RetentionStopEvent) -> None:
        while True:
            try:
                if stop_event.is_set():
                    return
            except Exception:
                self.report_unavailable()
                return
            try:
                observed_at = self._now()
            except Exception:
                self.report_unavailable()
                return
            try:
                report = self._cleanup(observed_at)
            except Exception:
                self._log.failed(observed_at=observed_at)
            else:
                self._log.completed(observed_at=observed_at, report=report)
            try:
                should_stop = stop_event.wait(RETENTION_INTERVAL_SECONDS)
            except Exception:
                self.report_unavailable(observed_at)
                return
            if should_stop:
                return

    def report_unavailable(self, observed_at: datetime | None = None) -> None:
        if observed_at is None:
            try:
                observed_at = self._now()
            except Exception:
                observed_at = datetime.now().astimezone()
        self._log.failed(observed_at=observed_at)
