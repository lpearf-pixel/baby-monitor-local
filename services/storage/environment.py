from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.events import EnvironmentReading, ReadingState


class DuplicateReadingError(RuntimeError):
    """Raised when a reading ID already exists."""


class StorageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class StoredEnvironmentIncident(StorageModel):
    incident_id: str = Field(min_length=1)
    kind: Literal["range", "unreadable"]
    state: Literal["open", "recovered"]
    severity: Literal["normal", "critical"]
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None = None
    reasons: tuple[str, ...] = ()
    opening_reading_id: str | None = None
    notified_levels: tuple[str, ...] = ()

    _aware_opened_at = field_validator("opened_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)
    _aware_recovered_at = field_validator("recovered_at")(_aware)

    @model_validator(mode="after")
    def require_recovery_time_matching_state(self) -> Self:
        if self.state == "open" and self.recovered_at is not None:
            raise ValueError("open incident cannot have recovered_at")
        if self.state == "recovered" and self.recovered_at is None:
            raise ValueError("recovered incident requires recovered_at")
        return self


class TrendWindow(StrEnum):
    HOURS_24 = "24h"
    DAYS_7 = "7d"


class EnvironmentTrendBucket(StorageModel):
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    availability_rate: float = Field(ge=0, le=1)
    temperature_min: float | None = None
    temperature_median: float | None = None
    temperature_max: float | None = None
    humidity_min: float | None = None
    humidity_median: float | None = None
    humidity_max: float | None = None

    _aware_started_at = field_validator("started_at")(_aware)
    _aware_ended_at = field_validator("ended_at")(_aware)


class EnvironmentTrend(StorageModel):
    window: TrendWindow
    bucket_seconds: int = Field(gt=0)
    started_at: datetime
    ended_at: datetime
    buckets: tuple[EnvironmentTrendBucket, ...]

    _aware_started_at = field_validator("started_at")(_aware)
    _aware_ended_at = field_validator("ended_at")(_aware)


class EnvironmentStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 1000")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS environment_readings (
                    reading_id TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    captured_epoch REAL NOT NULL,
                    fresh_until TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    temperature_c REAL,
                    humidity_rh REAL,
                    confidence REAL NOT NULL,
                    failure_reason TEXT,
                    calibration_version TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_environment_readings_captured
                    ON environment_readings(captured_epoch, reading_id);
                CREATE INDEX IF NOT EXISTS idx_environment_readings_state_captured
                    ON environment_readings(state, captured_epoch);

                CREATE TABLE IF NOT EXISTS environment_incidents (
                    incident_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recovered_at TEXT,
                    reasons_json TEXT NOT NULL,
                    opening_reading_id TEXT,
                    notified_levels_json TEXT NOT NULL,
                    FOREIGN KEY(opening_reading_id)
                        REFERENCES environment_readings(reading_id)
                );
                CREATE INDEX IF NOT EXISTS idx_environment_incidents_updated
                    ON environment_incidents(updated_at, incident_id);

                CREATE TABLE IF NOT EXISTS environment_state_snapshot (
                    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def append(self, reading: EnvironmentReading) -> None:
        try:
            with self._connect() as connection:
                self._insert_reading(connection, reading)
        except sqlite3.IntegrityError as exc:
            self._raise_reading_integrity(exc)

    @staticmethod
    def _insert_reading(
        connection: sqlite3.Connection,
        reading: EnvironmentReading,
    ) -> None:
        connection.execute(
            """
            INSERT INTO environment_readings (
                reading_id, captured_at, captured_epoch, fresh_until,
                source_kind, state, temperature_c, humidity_rh,
                confidence, failure_reason, calibration_version,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reading.reading_id,
                reading.captured_at.isoformat(),
                reading.captured_at.timestamp(),
                reading.fresh_until.isoformat(),
                reading.source_kind.value,
                reading.state.value,
                reading.temperature_c,
                reading.humidity_rh,
                reading.confidence,
                (
                    reading.failure_reason.value
                    if reading.failure_reason is not None
                    else None
                ),
                reading.calibration_version,
                reading.model_dump_json(),
            ),
        )

    @staticmethod
    def _raise_reading_integrity(exc: sqlite3.IntegrityError) -> None:
        if "environment_readings.reading_id" in str(exc):
            raise DuplicateReadingError("reading_id already exists") from exc
        raise exc

    def get(self, reading_id: str) -> EnvironmentReading | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM environment_readings WHERE reading_id = ?",
                (reading_id,),
            ).fetchone()
        return self._reading_from_row(row)

    def latest(self) -> EnvironmentReading | None:
        return self._latest_where("")

    def latest_available(self) -> EnvironmentReading | None:
        return self._latest_where("WHERE state = 'available'")

    def readings_after(
        self,
        *,
        captured_at: datetime | None,
        reading_id: str | None,
        limit: int = 1_000,
    ) -> tuple[EnvironmentReading, ...]:
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        if captured_at is None:
            clause = ""
            parameters: tuple[object, ...] = (limit,)
        else:
            if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                raise ValueError("captured_at must be timezone-aware")
            if reading_id is None:
                clause = "WHERE captured_epoch > ?"
                parameters = (captured_at.timestamp(), limit)
            else:
                clause = (
                    "WHERE captured_epoch > ? "
                    "OR (captured_epoch = ? AND reading_id > ?)"
                )
                parameters = (
                    captured_at.timestamp(),
                    captured_at.timestamp(),
                    reading_id,
                    limit,
                )
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json FROM environment_readings
                {clause}
                ORDER BY captured_epoch, reading_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return tuple(self._reading_from_row(row) for row in rows)  # type: ignore[misc]

    def _latest_where(self, clause: str) -> EnvironmentReading | None:
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT payload_json FROM environment_readings
                {clause}
                ORDER BY captured_epoch DESC, reading_id DESC
                LIMIT 1
                """
            ).fetchone()
        return self._reading_from_row(row)

    @staticmethod
    def _reading_from_row(row: sqlite3.Row | None) -> EnvironmentReading | None:
        if row is None:
            return None
        return EnvironmentReading.model_validate_json(row["payload_json"])

    def save_incident(self, incident: StoredEnvironmentIncident) -> None:
        with self._connect() as connection:
            self._upsert_incident(connection, incident)

    @staticmethod
    def _upsert_incident(
        connection: sqlite3.Connection,
        incident: StoredEnvironmentIncident,
    ) -> None:
        connection.execute(
            """
            INSERT INTO environment_incidents (
                incident_id, kind, state, severity, opened_at, updated_at,
                recovered_at, reasons_json, opening_reading_id,
                notified_levels_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(incident_id) DO UPDATE SET
                kind = excluded.kind,
                state = excluded.state,
                severity = excluded.severity,
                updated_at = excluded.updated_at,
                recovered_at = excluded.recovered_at,
                reasons_json = excluded.reasons_json,
                notified_levels_json = excluded.notified_levels_json
            """,
            (
                incident.incident_id,
                incident.kind,
                incident.state,
                incident.severity,
                incident.opened_at.isoformat(),
                incident.updated_at.isoformat(),
                (
                    incident.recovered_at.isoformat()
                    if incident.recovered_at is not None
                    else None
                ),
                json.dumps(incident.reasons, separators=(",", ":")),
                incident.opening_reading_id,
                json.dumps(incident.notified_levels, separators=(",", ":")),
            ),
        )

    def incidents(self, *, limit: int = 100) -> tuple[StoredEnvironmentIncident, ...]:
        if not 1 <= limit <= 1_000:
            raise ValueError("limit must be between 1 and 1000")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM environment_incidents
                ORDER BY updated_at DESC, incident_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._incident_from_row(row) for row in rows)

    def open_incidents(
        self,
        *,
        limit: int = 10,
    ) -> tuple[StoredEnvironmentIncident, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM environment_incidents
                WHERE state = 'open'
                ORDER BY updated_at, incident_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._incident_from_row(row) for row in rows)

    def incident(self, incident_id: str) -> StoredEnvironmentIncident | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM environment_incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        return self._incident_from_row(row) if row is not None else None

    @staticmethod
    def _incident_from_row(row: sqlite3.Row) -> StoredEnvironmentIncident:
        return StoredEnvironmentIncident(
            incident_id=row["incident_id"],
            kind=row["kind"],
            state=row["state"],
            severity=row["severity"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            recovered_at=(
                datetime.fromisoformat(row["recovered_at"])
                if row["recovered_at"] is not None
                else None
            ),
            reasons=tuple(json.loads(row["reasons_json"])),
            opening_reading_id=row["opening_reading_id"],
            notified_levels=tuple(json.loads(row["notified_levels_json"])),
        )

    def save_state_snapshot(
        self,
        payload: dict[str, Any],
        *,
        updated_at: datetime,
    ) -> None:
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        with self._connect() as connection:
            self._write_state_snapshot(connection, payload, updated_at=updated_at)

    @staticmethod
    def _write_state_snapshot(
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        *,
        updated_at: datetime,
    ) -> None:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO environment_state_snapshot (
                singleton_id, updated_at, payload_json
            ) VALUES (1, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                payload_json = excluded.payload_json
            """,
            (updated_at.isoformat(), serialized),
        )

    def commit_pipeline(
        self,
        *,
        reading: EnvironmentReading,
        incidents: tuple[StoredEnvironmentIncident, ...],
        state_snapshot: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        try:
            with self._connect() as connection:
                self._insert_reading(connection, reading)
                for incident in incidents:
                    self._upsert_incident(connection, incident)
                self._write_state_snapshot(
                    connection,
                    state_snapshot,
                    updated_at=updated_at,
                )
        except sqlite3.IntegrityError as exc:
            self._raise_reading_integrity(exc)

    def commit_state(
        self,
        *,
        incidents: tuple[StoredEnvironmentIncident, ...],
        state_snapshot: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        with self._connect() as connection:
            for incident in incidents:
                self._upsert_incident(connection, incident)
            self._write_state_snapshot(
                connection,
                state_snapshot,
                updated_at=updated_at,
            )

    def load_state_snapshot(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM environment_state_snapshot
                WHERE singleton_id = 1
                """
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            raise ValueError("environment snapshot must be an object")
        return payload

    def trend(
        self,
        window: TrendWindow,
        *,
        now: datetime,
    ) -> EnvironmentTrend:
        if not isinstance(window, TrendWindow):
            raise ValueError("window must be a closed TrendWindow")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if window is TrendWindow.HOURS_24:
            duration = timedelta(hours=24)
            bucket_seconds = 300
        else:
            duration = timedelta(days=7)
            bucket_seconds = 3_600
        started_at = now - duration
        bucket_count = round(duration.total_seconds() / bucket_seconds)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT captured_epoch, state, temperature_c, humidity_rh
                FROM environment_readings
                WHERE captured_epoch >= ? AND captured_epoch < ?
                ORDER BY captured_epoch, reading_id
                """,
                (started_at.timestamp(), now.timestamp()),
            ).fetchall()

        attempts: list[int] = [0 for _ in range(bucket_count)]
        temperatures: list[list[float]] = [[] for _ in range(bucket_count)]
        humidities: list[list[float]] = [[] for _ in range(bucket_count)]
        for row in rows:
            index = int((row["captured_epoch"] - started_at.timestamp()) // bucket_seconds)
            if not 0 <= index < bucket_count:
                continue
            attempts[index] += 1
            if row["state"] == ReadingState.AVAILABLE.value:
                temperatures[index].append(float(row["temperature_c"]))
                humidities[index].append(float(row["humidity_rh"]))

        buckets: list[EnvironmentTrendBucket] = []
        for index in range(bucket_count):
            bucket_start = started_at + timedelta(seconds=index * bucket_seconds)
            bucket_temperatures = temperatures[index]
            bucket_humidities = humidities[index]
            available_count = len(bucket_temperatures)
            sample_count = attempts[index]
            buckets.append(
                EnvironmentTrendBucket(
                    started_at=bucket_start,
                    ended_at=bucket_start + timedelta(seconds=bucket_seconds),
                    sample_count=sample_count,
                    available_count=available_count,
                    availability_rate=(
                        available_count / sample_count if sample_count else 0
                    ),
                    temperature_min=(
                        min(bucket_temperatures) if bucket_temperatures else None
                    ),
                    temperature_median=(
                        statistics.median(bucket_temperatures)
                        if bucket_temperatures
                        else None
                    ),
                    temperature_max=(
                        max(bucket_temperatures) if bucket_temperatures else None
                    ),
                    humidity_min=(min(bucket_humidities) if bucket_humidities else None),
                    humidity_median=(
                        statistics.median(bucket_humidities)
                        if bucket_humidities
                        else None
                    ),
                    humidity_max=(max(bucket_humidities) if bucket_humidities else None),
                )
            )
        return EnvironmentTrend(
            window=window,
            bucket_seconds=bucket_seconds,
            started_at=started_at,
            ended_at=now,
            buckets=tuple(buckets),
        )

    def cleanup(self, *, now: datetime, retention_days: int) -> int:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        cutoff = (now - timedelta(days=retention_days)).timestamp()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE environment_incidents
                SET opening_reading_id = NULL
                WHERE state = 'recovered'
                  AND opening_reading_id IN (
                      SELECT reading_id FROM environment_readings
                      WHERE captured_epoch < ?
                  )
                """,
                (cutoff,),
            )
            cursor = connection.execute(
                """
                DELETE FROM environment_readings
                WHERE captured_epoch < ?
                  AND reading_id NOT IN (
                      SELECT opening_reading_id
                      FROM environment_incidents
                      WHERE state = 'open' AND opening_reading_id IS NOT NULL
                  )
                """,
                (cutoff,),
            )
            return cursor.rowcount

    def integrity_check(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def journal_mode(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]).lower()
