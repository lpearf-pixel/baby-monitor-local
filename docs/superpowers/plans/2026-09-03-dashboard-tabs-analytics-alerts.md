# Compact Dashboard Tabs, Alerts, and Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the authenticated one-page Alpha Dashboard with a compact four-tab
shell that presents live overview, confirmed alerts, bounded `24h`/`7d` analytics and
closed system status without changing any detector, state machine or device control.

**Architecture:** Add closed Pydantic response contracts and one injected
`LocalDashboardService`. A dedicated Guardian SQLite reader operates in `mode=ro` plus
`query_only`; the aggregate service projects existing environment and gateway providers
without writing data. The browser remains framework-free: protected local CSS and three
small UMD modules own presentation, tab/refresh orchestration and lazy analytics while
the existing live viewer and calibration modules retain their lifecycles.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, native JavaScript UMD modules,
Canvas, Node's built-in test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-dashboard-tabs-analytics-alerts-design.md`

## Global Constraints

- Work only on `codex/dashboard-tabs-analytics-alerts`; starting implementation base is
  the planning commit descended from `cabd4cf10e35a4aa9877a9b3c9a1e8692818948d`.
- Do not rebase, merge, push, create a PR, or modify `main` or
  `stable/xiaomi-alpha` without fresh owner authority.
- Python is version 3.11 or newer. Use the project interpreter
  `./.venv-alpha/bin/python` when present; do not change `pyproject.toml` or install a new
  production dependency for this feature.
- Keep FastAPI plus native JavaScript. Do not add a bundler, SPA framework, CDN, network
  font, icon package or chart package.
- All new APIs and assets require the existing Basic Auth dependency and return
  `Cache-Control: no-store`.
- New query code is read-only. It must not migrate, create, repair, clean or write any
  SQLite database and must never contact a camera frame, start a worker or send a
  notification.
- Do not change Guardian/environment/Voice/Camera Reply decisions, thresholds, prompts,
  storage writers or notification dispatch. `camera_reply_enabled` stays false and PTZ
  stays disabled.
- Never expose household media, transcripts, model prose, evidence keys, database or
  local paths, private addresses, device identifiers, credentials or notification topics.
- Keep exactly one `/live.mjpeg` consumer and preserve the existing HD player, BFCache,
  snapshot, numeric zoom, fullscreen and calibration behavior.
- Server times are timezone-aware UTC; browser display uses `Intl.DateTimeFormat`.
- Current environment values never fall back to the last valid reading. Empty trend
  buckets stay `null`; zero-denominator rates stay `null`, not `0` or `100%`.
- Use TDD for every behavior task: observe the named RED failure, add the minimum
  production change, observe GREEN, run the task regression set, then commit.
- Run `git diff --check` before every commit and stage only the files named by that task.

## File and ownership map

| Path | Responsibility |
|---|---|
| `services/dashboard/contracts.py` | Closed public response models and enums only |
| `services/dashboard/guardian_query.py` | Read-only Guardian event/intervention/evidence/notification queries |
| `services/dashboard/service.py` | Environment, Guardian and gateway projection; priority and partial-failure policy |
| `services/storage/environment.py` | One fixed-window, query-only incident aggregate on the existing store |
| `services/environment/dashboard.py` | Forward the aggregate through the already-built environment service |
| `apps/api/alpha.py` | One provider protocol/field, authenticated routes/assets, semantic HTML shell |
| `apps/api/runtime.py` | Resolve the existing centralized data directory and inject one Dashboard service |
| `apps/api/dashboard.css` | Compact dark responsive styling and accessible state classes |
| `apps/api/dashboard_views.js` | Validate and render overview, unified alert and system responses |
| `apps/api/dashboard_shell.js` | Tab/hash behavior and one non-overlapping 15-second refresh scheduler |
| `apps/api/dashboard_analytics.js` | Lazy window fetch, analytics presentation and gap-preserving Canvas chart |
| `tests/dashboard/` | Python contract, SQLite query and aggregate-service tests |
| `tests/api/test_alpha_app.py` | Authentication, no-store, route and HTML compatibility tests |
| `tests/api/test_runtime.py` | Centralized path and runtime injection tests |
| `tests/frontend/dashboard_*.test.mjs` | Pure presenters, DOM behavior, scheduling, chart and stale-data tests |

Do not modify `guardian_events.js` or `environment_dashboard.js` merely to reuse code.
Their old endpoints and standalone tests remain compatibility evidence; the new shell
uses the normalized Dashboard responses and does not load the two old auto-mounting
scripts, which prevents duplicate polling.

## Execution preflight

- [x] Verify branch and clean state:

  ```bash
  test "$(git branch --show-current)" = "codex/dashboard-tabs-analytics-alerts"
  test -z "$(git status --porcelain)"
  git rev-parse HEAD
  git log --oneline --decorate -3
  ```

- [x] Verify the JavaScript baseline:

  ```bash
  node --test tests/frontend/*.test.mjs
  ```

  Expected: the existing 73 tests pass before a frontend file changes.

- [x] Verify a usable Python environment before starting Task 1:

  ```bash
  test -x ./.venv-alpha/bin/python
  ./.venv-alpha/bin/python -c 'import fastapi, httpx, httpx2, pydantic, pytest; print("dashboard_test_runtime=ready")'
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py tests/events/test_guardian_query.py
  ```

  Expected: the readiness line prints and the two existing suites pass. The current
  planning sandbox did not contain `.venv-alpha` or `pytest`; that is an environment
  blocker, not passing Python evidence. On the Intel i9, use the existing
  `make alpha-install` workflow. Do not run the macOS installer in a Linux sandbox and
  do not begin Python TDD until RED can actually execute.

---

### Task 1: Define closed Dashboard response contracts

**Files:**
- Create: `services/dashboard/__init__.py`
- Create: `services/dashboard/contracts.py`
- Create: `tests/dashboard/__init__.py`
- Create: `tests/dashboard/test_contracts.py`

**Interfaces:**
- Consumes: Pydantic v2 and timezone-aware `datetime`.
- Produces: `DashboardWindow`, `DashboardAlertV1`, `DashboardComponentV1`,
  `DashboardEnvironmentCurrentV1`, `DashboardOverviewV1`,
  `DashboardAlertListV1`, `DashboardTrendBucketV1`,
  `DashboardGuardianAnalyticsV1`, `DashboardEnvironmentAnalyticsV1`,
  `DashboardAnalyticsV1`, and `DashboardSystemV1`.

- [x] **Step 1: Write contract tests that fail because the module does not exist**

  Add tests with one fixed aware timestamp and prove all three safety properties:

  ```python
  from datetime import UTC, datetime

  import pytest
  from pydantic import ValidationError

  from services.dashboard.contracts import (
      DashboardAlertV1,
      DashboardEnvironmentAnalyticsV1,
      DashboardEnvironmentCurrentV1,
      DashboardEnvironmentIncidentCountsV1,
      DashboardWindow,
  )


  NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


  def test_alert_contract_rejects_extra_candidate_state_and_naive_time() -> None:
      values = {
          "alert_id": "guardian:event-1",
          "source": "guardian",
          "kind": "face_not_visible",
          "state": "open",
          "priority": "critical",
          "opened_at": NOW,
          "updated_at": NOW,
          "recovered_at": None,
          "reason_codes": (),
          "adult_intervention_count": 0,
          "evidence_state": "collecting",
          "notification_state": "pending",
          "resolution_cause": None,
      }
      assert DashboardAlertV1(**values).state == "open"
      with pytest.raises(ValidationError):
          DashboardAlertV1(**values, candidate_state="watch")
      with pytest.raises(ValidationError):
          DashboardAlertV1(**{**values, "opened_at": NOW.replace(tzinfo=None)})


  def test_unavailable_current_cannot_contain_current_values() -> None:
      with pytest.raises(ValidationError):
          DashboardEnvironmentCurrentV1(
              state="unavailable",
              temperature_c=23.0,
              humidity_rh=50.0,
              captured_at=NOW,
              fresh_until=NOW,
              failure_reason="environment_no_reading",
              last_valid_temperature_c=None,
              last_valid_humidity_rh=None,
              last_valid_captured_at=None,
          )


  def test_analytics_allows_none_but_not_fabricated_out_of_range_rates() -> None:
      assert DashboardWindow("24h") is DashboardWindow.HOURS_24
      with pytest.raises(ValidationError):
          DashboardEnvironmentAnalyticsV1(
              state="available",
              sample_count=1,
              available_count=1,
              availability_rate=1.2,
              incident_counts=DashboardEnvironmentIncidentCountsV1(
                  range_normal=0,
                  range_critical=0,
                  unreadable=0,
              ),
              buckets=(),
          )
  ```

  Add coherent recovered-alert coverage: `recovered_at` must be present, equal to or
  later than `opened_at`, and not later than `updated_at`; an open alert cannot contain
  `recovered_at` or `resolution_cause`.

- [x] **Step 2: Run the contract test and observe RED**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/dashboard/test_contracts.py
  ```

  Expected: collection fails with `ModuleNotFoundError: services.dashboard`.

- [x] **Step 3: Add the exact enums and closed model base**

  In `services/dashboard/contracts.py`, use one frozen/forbid base and the following
  closed values:

  ```python
  from __future__ import annotations

  from datetime import datetime
  from enum import StrEnum
  from typing import Literal, Self

  from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


  class DashboardModel(BaseModel):
      model_config = ConfigDict(extra="forbid", frozen=True)


  def require_aware(value: datetime | None) -> datetime | None:
      if value is not None and (value.tzinfo is None or value.utcoffset() is None):
          raise ValueError("datetime must be timezone-aware")
      return value


  class DashboardWindow(StrEnum):
      HOURS_24 = "24h"
      DAYS_7 = "7d"


  DashboardSource = Literal["guardian", "environment", "system"]
  DashboardPriority = Literal["critical", "warning", "info"]
  DashboardAlertState = Literal["open", "recovered"]
  DashboardSectionState = Literal["available", "unavailable"]
  DashboardComponentState = Literal[
      "healthy", "degraded", "unavailable", "disabled"
  ]
  DashboardEvidenceState = Literal[
      "collecting", "ready", "failed", "interrupted", "unavailable"
  ]
  DashboardNotificationState = Literal[
      "pending", "delivered", "rejected", "mixed", "unavailable"
  ]
  DashboardResolutionCause = Literal["explicit_safe", "subject_outside"]
  DashboardAlertKind = Literal[
      "face_not_visible",
      "prone_candidate",
      "outside_candidate",
      "environment_range",
      "environment_unreadable",
      "camera_status",
      "guardian_query_status",
      "environment_query_status",
      "notification_queue_status",
      "calibration_status",
  ]
  DashboardComponentId = Literal[
      "camera",
      "guardian_query",
      "environment",
      "gauge_calibration",
      "notification_queue",
      "visual",
      "voice",
      "camera_reply",
  ]
  DashboardReasonCode = Literal[
      "temperature_low",
      "temperature_high",
      "temperature_critical_low",
      "temperature_critical_high",
      "humidity_low",
      "humidity_high",
      "humidity_critical_low",
      "humidity_critical_high",
      "reading_unavailable",
      "no_new_reading",
      "calibration_missing",
      "calibration_invalid",
      "frame_source_unavailable",
      "frame_stale",
      "roi_out_of_bounds",
      "too_dark",
      "glare",
      "occluded",
      "needle_not_found",
      "insufficient_valid_frames",
      "inconsistent_frames",
      "low_confidence",
      "internal_error",
      "environment_no_reading",
      "camera_online",
      "camera_offline",
      "camera_unavailable",
      "guardian_query_available",
      "guardian_query_unavailable",
      "environment_available",
      "environment_unavailable",
      "notification_queue_empty",
      "notification_queue_pending",
      "notification_query_unavailable",
      "calibration_available",
      "camera_reply_disabled",
      "camera_reply_status_unavailable",
  ]
  ```

- [x] **Step 4: Add the complete public models and invariants**

  Implement these exact field sets; every timestamp field uses `require_aware` and all
  tuples have the stated maximum:

  ```python
  class DashboardAlertV1(DashboardModel):
      alert_id: str = Field(min_length=1, max_length=160)
      source: DashboardSource
      kind: DashboardAlertKind
      state: DashboardAlertState
      priority: DashboardPriority
      opened_at: datetime
      updated_at: datetime
      recovered_at: datetime | None = None
      reason_codes: tuple[DashboardReasonCode, ...] = Field(max_length=8)
      adult_intervention_count: int | None = Field(default=None, ge=0)
      evidence_state: DashboardEvidenceState | None = None
      notification_state: DashboardNotificationState | None = None
      resolution_cause: DashboardResolutionCause | None = None

      _aware_times = field_validator(
          "opened_at", "updated_at", "recovered_at"
      )(require_aware)

      @model_validator(mode="after")
      def require_lifecycle(self) -> Self:
          if self.updated_at < self.opened_at:
              raise ValueError("updated_at cannot precede opened_at")
          if self.state == "open":
              if self.recovered_at is not None or self.resolution_cause is not None:
                  raise ValueError("open alert cannot contain recovery data")
          elif self.recovered_at is None:
              raise ValueError("recovered alert requires recovered_at")
          elif not self.opened_at <= self.recovered_at <= self.updated_at:
              raise ValueError("recovery time must be inside the lifecycle")
          return self


  class DashboardComponentV1(DashboardModel):
      component_id: DashboardComponentId
      state: DashboardComponentState
      reason_code: DashboardReasonCode
      updated_at: datetime

      _aware_updated_at = field_validator("updated_at")(require_aware)


  class DashboardEnvironmentCurrentV1(DashboardModel):
      state: Literal["available", "unavailable"]
      temperature_c: float | None = Field(default=None, ge=-50, le=60)
      humidity_rh: float | None = Field(default=None, ge=0, le=100)
      captured_at: datetime | None = None
      fresh_until: datetime | None = None
      failure_reason: DashboardReasonCode | None = None
      last_valid_temperature_c: float | None = Field(default=None, ge=-50, le=60)
      last_valid_humidity_rh: float | None = Field(default=None, ge=0, le=100)
      last_valid_captured_at: datetime | None = None

      _aware_times = field_validator(
          "captured_at", "fresh_until", "last_valid_captured_at"
      )(require_aware)
  ```

  Add one `model_validator` to `DashboardEnvironmentCurrentV1`: available requires both
  current values, `captured_at`, `fresh_until`, no failure reason and
  `fresh_until > captured_at`; unavailable forbids both current values. Last-valid
  temperature, humidity and timestamp must be all present or all absent.

  Add the remaining models with these exact fields:

  | Model | Fields |
  |---|---|
  | `DashboardAttentionV1` | `alert: DashboardAlertV1`, `additional_open_count: int >= 0` |
  | `DashboardOverviewV1` | `schema_version: Literal[1]`, `generated_at`, `attention`, `open_alert_count`, nullable `guardian_open_count`, nullable `today_recovered_count`, `environment`, `components` max 8, `recent_activity` max 10 |
  | `DashboardAlertListV1` | `schema_version`, `generated_at`, `alerts` max 100 |
  | `DashboardTrendBucketV1` | `started_at`, `ended_at`, sample/available counts, nullable rate 0..1, nullable temperature/humidity min/median/max |
  | `DashboardRiskCountsV1` | `face_not_visible`, `prone_candidate`, `outside_candidate`, all non-negative |
  | `DashboardEvidenceCountsV1` | collecting/ready/failed/interrupted/retained_total/missing, all non-negative, `ready_rate` nullable 0..1 |
  | `DashboardNotificationCountsV1` | pending/delivered/rejected/terminal_total, all non-negative, `success_rate` nullable 0..1 |
  | `DashboardEnvironmentIncidentCountsV1` | range_normal/range_critical/unreadable, all non-negative |
  | `DashboardGuardianAnalyticsV1` | `state`, confirmed/recovered/intervention counts, nullable recovery median, risk/evidence/notification models |
  | `DashboardEnvironmentAnalyticsV1` | `state`, sample/available counts, nullable availability rate, incident counts, buckets max 288 |
  | `DashboardAnalyticsV1` | `schema_version`, `generated_at`, `window`, `started_at`, `ended_at`, environment, guardian |
  | `DashboardSystemV1` | `schema_version`, `generated_at`, components max 8 |

  Add coherence validators: `available_count <= sample_count`; bucket availability is
  `available_count / sample_count` when samples exist and `None` otherwise; each bucket
  ends after it starts; each temperature/humidity min/median/max triple is wholly null
  when no available samples and wholly present plus ordered when samples are available.
  `retained_total` equals the sum of
  the four retained evidence states; `ready_rate = ready / retained_total` when retained
  total is positive and is `None` otherwise. `terminal_total = delivered + rejected`;
  notification success is `delivered / terminal_total` when positive and `None`
  otherwise. Analytics ends after it starts, its duration is exactly 24 hours or 7 days
  for the selected enum, and an available environment section has exactly 288 five-minute
  contiguous buckets or 168 contiguous hourly buckets covering that same window. Its
  aggregate counts/rate
  equal the bucket sums/weighted rate. An unavailable environment section has zero
  counts, null rate and no buckets. Require unique alert IDs and component IDs in every
  response tuple.

- [x] **Step 5: Run contract GREEN and task regression**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/dashboard/test_contracts.py
  ./.venv-alpha/bin/python -m compileall -q services/dashboard
  git diff --check
  ```

  Expected: all contract tests pass and compilation/diff checks return zero.

- [x] **Step 6: Commit Task 1**

  ```bash
  git add services/dashboard/__init__.py services/dashboard/contracts.py \
    tests/dashboard/__init__.py tests/dashboard/test_contracts.py
  git commit -m "feat: define dashboard response contracts"
  ```

### Task 2: Add the read-only Guardian analytics query

**Files:**
- Create: `services/dashboard/guardian_query.py`
- Create: `tests/dashboard/test_guardian_query.py`

**Interfaces:**
- Consumes: `DashboardWindow` and Dashboard contract models from Task 1; existing
  `events.sqlite3` tables created by `VisualRiskEventStore`.
- Produces: `GuardianDashboardQuery(database_path: Path)`,
  `GuardianDashboardQuery.alerts() -> tuple[DashboardAlertV1, ...]`,
  `GuardianDashboardQuery.analytics(window, now) -> DashboardGuardianAnalyticsV1`,
  `GuardianDashboardQuery.recovered_count(started_at, ended_at) -> int`,
  `GuardianDashboardQuery.notification_component(now) -> DashboardComponentV1`, and
  `GuardianDashboardQueryUnavailable`.

- [x] **Step 1: Write missing/read-only and closed-projection RED tests**

  Use `VisualRiskEventStore(tmp_path / "events.sqlite3").migrate()` only in test setup.
  Insert fixed rows through the store where possible and fixed SQL for notification and
  evidence state combinations. Add these tests:

  ```python
  def test_missing_database_fails_without_creating_it(tmp_path: Path) -> None:
      database = tmp_path / "missing.sqlite3"
      with pytest.raises(GuardianDashboardQueryUnavailable):
          GuardianDashboardQuery(database).alerts()
      assert not database.exists()


  def test_alerts_return_all_open_then_fill_with_latest_recovered(tmp_path: Path) -> None:
      database = create_database(tmp_path)
      insert_event(database, event_id="old-open", state="open", updated_at=NOW)
      for index in range(105):
          insert_event(
              database,
              event_id=f"recovered-{index:03d}",
              state="recovered",
              updated_at=NOW + timedelta(minutes=index + 1),
          )
      alerts = GuardianDashboardQuery(database).alerts()
      assert len(alerts) == 100
      assert alerts[0].alert_id == "guardian:old-open"
      assert alerts[0].state == "open"
      assert {item.source for item in alerts} == {"guardian"}


  def test_alert_projection_aggregates_notification_without_media_fields(
      tmp_path: Path,
  ) -> None:
      database = create_database(tmp_path)
      insert_ready_event_and_notifications(database, now=NOW)
      payload = GuardianDashboardQuery(database).alerts()[0].model_dump(mode="json")
      assert payload["notification_state"] == "mixed"
      assert payload["evidence_state"] == "ready"
      assert payload["resolution_cause"] is None
      assert not any(
          word in str(payload).lower()
          for word in ("confidence", "rule_version", "snapshot", "clip", "path")
      )
  ```

  Add a query-only test that records `connection.set_trace_callback` through an injected
  connection factory and asserts no statement begins with `INSERT`, `UPDATE`, `DELETE`,
  `CREATE`, `DROP`, `ALTER`, `REPLACE` or `VACUUM`.

- [x] **Step 2: Run the Guardian query test and observe RED**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/dashboard/test_guardian_query.py
  ```

  Expected: collection fails because `services.dashboard.guardian_query` is absent.

- [x] **Step 3: Implement the read-only connection and alert selection**

  Use one injectable connection factory while production always opens the fixed URI:

  ```python
  class GuardianDashboardQueryUnavailable(RuntimeError):
      pass


  class GuardianDashboardQuery:
      def __init__(
          self,
          database_path: Path,
          *,
          connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
      ) -> None:
          self._database_path = Path(database_path)
          self._connect = connect

      @contextmanager
      def _connection(self) -> Iterator[sqlite3.Connection]:
          if not self._database_path.is_file():
              raise GuardianDashboardQueryUnavailable
          uri = f"{self._database_path.resolve().as_uri()}?mode=ro"
          try:
              with self._connect(uri, uri=True, timeout=1.0) as connection:
                  connection.row_factory = sqlite3.Row
                  connection.execute("PRAGMA query_only = ON")
                  yield connection
          except (sqlite3.Error, ValueError, ValidationError) as exc:
              raise GuardianDashboardQueryUnavailable from exc
  ```

  Query all `state='open'` rows plus the newest recovered rows required to fill a maximum
  of 100. Join evidence and aggregate notification counts by event. Map event IDs to
  `guardian:<event_id>`, open Guardian priority to `critical` and recovered Guardian
  priority to `info`, risk kind directly to the closed Dashboard kind, and missing
  evidence/notification to `unavailable`. Notification
  state is the sole state when all rows agree and `mixed` when two or more states occur.
  Sort open first, then priority, `updated_at` descending and stable ID descending before
  truncating to 100. Do not select confidence, rule version, evidence keys or result prose.

- [x] **Step 4: Add analytics RED tests for exact window boundaries and denominators**

  Insert rows one second before, exactly at, and one second after each boundary. Assert:

  ```python
  metrics = GuardianDashboardQuery(database).analytics(
      DashboardWindow.HOURS_24,
      NOW,
  )
  assert metrics.state == "available"
  assert metrics.confirmed_event_count == 3
  assert metrics.recovered_event_count == 2
  assert metrics.recovery_median_seconds == 90.0
  assert metrics.adult_intervention_count == 2
  assert metrics.risk_counts.model_dump() == {
      "face_not_visible": 1,
      "prone_candidate": 1,
      "outside_candidate": 1,
  }
  assert metrics.evidence.ready_rate == 0.5
  assert metrics.evidence.missing == 1
  assert metrics.notifications.pending == 1
  assert metrics.notifications.terminal_total == 2
  assert metrics.notifications.success_rate == 0.5
  ```

  The event opened exactly at `started_at` is included; an event opened exactly at
  `ended_at` is excluded. Interventions use `visual_interventions.observed_at` and count
  unique intervention rows, not cumulative event counters. Recovery uses
  `recovered_at` in the window. Notification terminal rate uses only delivered/rejected
  rows whose `updated_at` is in the window; pending is counted at query time and excluded
  from the terminal denominator.

  Add `recovered_count(started_at, ended_at)` boundary coverage. It accepts only two
  aware datetimes with `ended_at > started_at` and counts `recovered_at` in the same
  half-open interval. This method supplies the overview's project-timezone natural-day
  count and must not reuse the rolling 24-hour count.

- [x] **Step 5: Implement fixed analytics queries and notification health**

  Add one fixed-duration helper and return only the contract model:

  ```python
  def window_start(window: DashboardWindow, now: datetime) -> datetime:
      if now.tzinfo is None or now.utcoffset() is None:
          raise ValueError("now must be timezone-aware")
      duration = timedelta(hours=24) if window is DashboardWindow.HOURS_24 else timedelta(days=7)
      return now - duration
  ```

  Use fixed SQL statements over `visual_risk_events`, `visual_interventions`,
  `visual_risk_evidence` and `visual_risk_notifications`. Parse all returned timestamps
  with `datetime.fromisoformat` before constructing contracts. Compute median with
  `statistics.median`; never ask SQLite for a free-form expression supplied by a client.

  `notification_component(now)` returns:

  - `healthy/notification_queue_empty` when the query succeeds and pending is zero;
  - `degraded/notification_queue_pending` when pending is positive;
  - it raises `GuardianDashboardQueryUnavailable` when the table/query is unavailable.

  Implement `recovered_count` with one fixed SQL statement and the same read-only
  connection. Do not accept a timezone name or user-provided SQL at this layer.

- [x] **Step 6: Run Task 2 GREEN and existing Guardian regression**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q \
    tests/dashboard/test_guardian_query.py \
    tests/events/test_guardian_query.py \
    tests/storage/test_visual_risk_store.py
  ./.venv-alpha/bin/python -m compileall -q services/dashboard
  git diff --check
  ```

- [x] **Step 7: Commit Task 2**

  ```bash
  git add services/dashboard/guardian_query.py tests/dashboard/test_guardian_query.py
  git commit -m "feat: query dashboard guardian analytics read only"
  ```

### Task 3: Build the partial-failure aggregate Dashboard service

**Files:**
- Modify: `services/storage/environment.py`
- Modify: `services/environment/dashboard.py`
- Create: `services/dashboard/service.py`
- Modify: `tests/storage/test_environment_store.py`
- Create: `tests/environment/test_dashboard.py`
- Create: `tests/dashboard/test_service.py`

**Interfaces:**
- Consumes: `GuardianDashboardQuery`; existing environment methods `current(now)`,
  `trend(window, now)`, `incidents()`, `calibration_status()` plus the fixed-window
  `incident_counts(started_at, ended_at)` added below; gateway `status()`.
- Produces: `LocalDashboardService.overview(now)`, `alerts(now)`,
  `analytics(window, now)`, and `system(now)` matching the Task 1 contracts, plus the
  stable aggregate-level `DashboardServiceUnavailable` exception.

- [x] **Step 1: Write exact environment incident-count RED tests**

  In `tests/storage/test_environment_store.py`, save more than 100 incidents and include
  rows immediately before, exactly at and exactly after the requested boundaries. Prove
  the count is not derived from the existing 100-row list:

  ```python
  counts = store.incident_counts(
      started_at=NOW - timedelta(days=7),
      ended_at=NOW,
  )
  assert counts.range_normal == 101
  assert counts.range_critical == 2
  assert counts.unreadable == 3
  ```

  The row at `started_at` is included and the row at `ended_at` is excluded. Add
  `tests/environment/test_dashboard.py` with a recording fake store and assert
  `LocalEnvironmentDashboardService.incident_counts()` forwards the two aware boundaries
  exactly once without calling `incidents()`.

  ```bash
  ./.venv-alpha/bin/python -m pytest -q \
    tests/storage/test_environment_store.py -k incident_counts \
    tests/environment/test_dashboard.py
  ```

  Expected: `EnvironmentStore` and `LocalEnvironmentDashboardService` do not yet expose
  `incident_counts`.

- [x] **Step 2: Implement one bounded read method on the existing environment service**

  Add frozen `EnvironmentIncidentCounts` with non-negative `range_normal`,
  `range_critical` and `unreadable` fields to `services/storage/environment.py`. Add
  `EnvironmentStore.incident_counts(*, started_at, ended_at)` that rejects naive or
  inverted boundaries, opens the already configured store connection, immediately sets
  `PRAGMA query_only = ON`, and executes one fixed `SUM(CASE ...)` query over
  `environment_incidents.opened_at` in `[started_at, ended_at)` using fixed
  `julianday(...)` comparisons. It must not call
  `incidents()`, interpolate SQL, migrate or write. Add a one-line forwarding method to
  `LocalEnvironmentDashboardService`; the Dashboard aggregate reuses this already-built
  service and never constructs another `EnvironmentStore`.

  Run the Step 1 command again and require GREEN, then run:

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/storage/test_environment_store.py \
    tests/environment/test_dashboard.py
  git diff --check
  ```

- [x] **Step 3: Write aggregate RED tests with small fakes**

  Define fakes that count calls and return an unavailable current reading plus a separate
  last-valid reading. Add tests for the highest-risk selection, candidate exclusion by
  construction, partial failure and stale semantics:

  ```python
  def test_overview_keeps_unavailable_current_separate_and_selects_critical_attention() -> None:
      service = LocalDashboardService(
          camera=FakeCamera({"camera": "online", "detail": "private-value"}),
          guardian=FakeGuardian(alerts=(guardian_open_alert(),)),
          environment=FakeEnvironment(snapshot=unavailable_snapshot()),
          camera_reply_enabled=False,
          timezone_name="Asia/Shanghai",
      )
      result = service.overview(NOW)
      assert result.attention is not None
      assert result.attention.alert.alert_id == "guardian:event-open"
      assert result.environment.state == "unavailable"
      assert result.environment.temperature_c is None
      assert result.environment.last_valid_temperature_c == 22.0
      assert "private-value" not in str(result.model_dump())


  def test_guardian_failure_preserves_environment_and_emits_stable_system_warning() -> None:
      service = LocalDashboardService(
          camera=FakeCamera({"camera": "online"}),
          guardian=FailingGuardian(),
          environment=FakeEnvironment(snapshot=available_snapshot()),
          camera_reply_enabled=False,
          timezone_name="Asia/Shanghai",
      )
      result = service.alerts(NOW)
      assert any(item.kind == "guardian_query_status" for item in result.alerts)
      assert any(item.source == "environment" for item in result.alerts)
      assert "sqlite" not in str(result.model_dump()).lower()
  ```

  Add cases for: critical environment before warning system alert; all open items retained
  before recovered history; Camera Reply disabled without a warning; raw gateway `detail`,
  stream lists and exception types absent; environment query failure does not erase a
  Guardian alert. When the Guardian query is unavailable, assert
  `guardian_open_count is None` and `today_recovered_count is None`, not zero; a successful
  empty Guardian query returns zero for both.

- [x] **Step 4: Run service tests and observe RED**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/dashboard/test_service.py
  ```

  Expected: collection fails because `services.dashboard.service` is absent.

- [x] **Step 5: Implement provider protocols and closed projections**

  Define protocols with the exact methods used by the constructor and keep them free of
  `apps.api` imports. Import `ZoneInfo` from Python's standard `zoneinfo` module:

  ```python
  class CameraStatusProvider(Protocol):
      def status(self) -> dict[str, object]: ...


  class EnvironmentDashboardProvider(Protocol):
      def current(self, now: datetime) -> EnvironmentSnapshot: ...
      def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend: ...
      def incidents(self) -> tuple[EnvironmentIncident, ...]: ...
      def incident_counts(
          self, *, started_at: datetime, ended_at: datetime
      ) -> EnvironmentIncidentCounts: ...
      def calibration_status(self) -> dict[str, object]: ...


  class GuardianDashboardProvider(Protocol):
      def alerts(self) -> tuple[DashboardAlertV1, ...]: ...
      def recovered_count(self, started_at: datetime, ended_at: datetime) -> int: ...
      def analytics(
          self, window: DashboardWindow, now: datetime
      ) -> DashboardGuardianAnalyticsV1: ...
      def notification_component(self, now: datetime) -> DashboardComponentV1: ...
  ```

  Implement:

  ```python
  class LocalDashboardService:
      def __init__(
          self,
          *,
          camera: CameraStatusProvider,
          guardian: GuardianDashboardProvider | None,
          environment: EnvironmentDashboardProvider | None,
          camera_reply_enabled: bool,
          timezone_name: str,
      ) -> None:
          self._camera = camera
          self._guardian = guardian
          self._environment = environment
          self._camera_reply_enabled = camera_reply_enabled
          self._timezone = ZoneInfo(timezone_name)
  ```

  Define `DashboardServiceUnavailable(RuntimeError)` beside the service. Catch expected
  provider/query/row-validation failures inside the smallest affected projection and
  return that section/component as unavailable. Raise `DashboardServiceUnavailable`
  only if the aggregate cannot construct a valid top-level closed response; never place
  the source exception text in the raised message.

  Projection rules are exact:

  - camera `online` becomes `healthy/camera_online`; `offline` becomes
    `unavailable/camera_offline`; every other/malformed value becomes
    `unavailable/camera_unavailable`; ignore every other gateway field;
  - absent Guardian provider becomes `unavailable/guardian_query_unavailable`;
  - absent environment becomes `unavailable/environment_unavailable` and has no values;
  - current reading is available only when the existing snapshot says
    `current_available=True` and both values exist; otherwise current values are null;
  - an absent current reading uses `environment_no_reading`, an otherwise available but
    expired reading uses `no_new_reading`, and an upstream unavailable reading uses its
    accepted closed failure reason or falls back to `reading_unavailable`; never copy an
    unrecognized reason;
  - the environment component is `healthy/environment_available` only for an available
    current reading and otherwise `unavailable/<the closed reason above>`;
  - calibration `available` maps to `healthy/calibration_available`, `missing` to
    `degraded/calibration_missing`, and `invalid` or an unexpected value to
    `unavailable/calibration_invalid`; ignore calibration IDs and paths;
  - notification pending maps to `degraded/notification_queue_pending`, empty to
    `healthy/notification_queue_empty`, and a failed query to
    `unavailable/notification_query_unavailable`;
  - Camera Reply false becomes `disabled/camera_reply_disabled`; true without a stable
    runtime health provider becomes `unavailable/camera_reply_status_unavailable`, and
    the test must make this state visible rather than healthy.

  Return components in the fixed order `camera`, `guardian_query`, `environment`,
  `gauge_calibration`, `notification_queue`, `camera_reply`. The current `AlphaRuntime`
  exposes no authoritative visual-worker or Voice-worker health provider, so omit those
  two optional components rather than inferring health from settings or page reachability;
  their closed component IDs remain reserved for a future real provider.

  Compute `today_recovered_count` from the natural day in `self._timezone`: convert
  `now` to that zone, replace hour/minute/second/microsecond with zero, convert the start
  back to UTC, then call `guardian.recovered_count(day_start_utc, now)`. Add a test at
  `00:30 Asia/Shanghai` proving a recovery at the previous local date is excluded while
  one at `00:00` is included. Response timestamps remain UTC.
  Compute `guardian_open_count` from the successful Guardian alert projection only. Both
  Guardian counts are `None` when that source fails so the overview never turns unknown
  into zero; `open_alert_count` remains the count of known unified open rows, including a
  stable Guardian-query system warning.

- [x] **Step 6: Implement unified environment/system alerts and ordering**

  Map environment incident IDs to `environment:<incident_id>`, range kind to
  `environment_range`, unreadable kind to `environment_unreadable`, critical range to
  `critical`, and all other open environment items to `warning`. Recovered incidents are
  `info`. Copy only reason values accepted by `DashboardReasonCode`.

  Create system alerts only for degraded/unavailable camera, Guardian query,
  environment query, notification queue or calibration components. Do not create an
  alert for `camera_reply` when disabled. When an open persisted unreadable incident
  already represents the current environment failure, omit the duplicate environment
  component alert.

  A system snapshot alert uses stable ID `system:<component_id>`, its fixed component-to-
  kind mapping, `state="open"`, `priority="warning"`, and the component timestamp for
  both `opened_at` and `updated_at`. It never fabricates a recovered history row. Add
  exact-ID tests so repeated refreshes address the same row even though the timestamp may
  advance.

  Merge `EnvironmentSnapshot.open_incidents` with the bounded historical
  `environment.incidents()` result by `incident_id`, preferring the snapshot copy. This
  guarantees that an old current incident cannot be starved by 100 newer recovered rows.
  Add a test with exactly that shape and assert the old open incident remains in the
  unified result.

  Use stable multi-pass sorting so the final string tie-break can be descending without
  character-code tricks:

  ```python
  PRIORITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


  def order_alerts(items: Iterable[DashboardAlertV1]) -> tuple[DashboardAlertV1, ...]:
      ordered = sorted(items, key=lambda item: item.alert_id, reverse=True)
      ordered.sort(key=lambda item: item.updated_at, reverse=True)
      ordered.sort(key=lambda item: PRIORITY_ORDER[item.priority])
      ordered.sort(key=lambda item: 0 if item.state == "open" else 1)
      return tuple(ordered)
  ```

  Sort all open items before adding newest recovered items to the 100-item bound. For
  attention, do not reuse the list order: among open items choose highest priority, then
  earliest `opened_at`, then stable `alert_id` descending; set
  `additional_open_count` to the remaining number. Add a test where a newer critical
  item has a later `updated_at` but the older-opened critical item wins attention.
  Overview recent activity is the first 10 unified list items.

- [x] **Step 7: Add analytics projection RED tests**

  Assert weighted environment availability and partial source failure:

  ```python
  result = service.analytics(DashboardWindow.HOURS_24, NOW)
  assert result.environment.sample_count == 10
  assert result.environment.available_count == 7
  assert result.environment.availability_rate == 0.7
  assert result.environment.buckets[1].temperature_median is None
  assert result.guardian.confirmed_event_count == 3
  ```

  Add a zero-sample case expecting both bucket and aggregate `availability_rate is None`,
  a 24-hour case expecting exactly 288 five-minute buckets, a 7-day case expecting exactly
  168 hourly buckets, an environment exception case that leaves the Guardian
  section available, and a Guardian exception case that leaves environment analytics
  available. No exception string may enter the model.

- [x] **Step 8: Implement bounded analytics projection**

  Convert `DashboardWindow.HOURS_24` to existing `TrendWindow.HOURS_24` and
  `DashboardWindow.DAYS_7` to `TrendWindow.DAYS_7`. Sum sample/available counts across
  buckets and calculate the weighted rate only when sample count is positive. Convert the
  existing provider's zero-sample bucket rate from `0` to `None`; copy all min/median/max
  fields without filling nulls. Count environment incidents by
  calling `environment.incident_counts(started_at=started_at, ended_at=now)`; never count
  the bounded `incidents()` display list. Return an unavailable section with zero counts,
  null rates and an empty bucket tuple when one provider fails; preserve the other
  section.

- [x] **Step 9: Run Task 3 GREEN and focused existing regressions**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q \
    tests/dashboard/test_service.py \
    tests/environment/test_dashboard.py \
    tests/environment/test_snapshot_provider.py \
    tests/storage/test_environment_store.py \
    tests/storage/test_environment_trends.py \
    tests/events/test_guardian_query.py
  ./.venv-alpha/bin/python -m compileall -q \
    services/dashboard services/environment/dashboard.py services/storage/environment.py
  git diff --check
  ```

- [x] **Step 10: Commit Task 3**

  ```bash
  git add services/dashboard/service.py services/environment/dashboard.py \
    services/storage/environment.py tests/dashboard/test_service.py \
    tests/environment/test_dashboard.py tests/storage/test_environment_store.py
  git commit -m "feat: aggregate dashboard status and alerts"
  ```

### Task 4: Inject the service and expose authenticated data APIs

**Files:**
- Modify: `apps/api/alpha.py:56-74,143-156,328-525`
- Modify: `apps/api/runtime.py:1-18,163-210`
- Modify: `tests/api/test_alpha_app.py:15-280`
- Modify: `tests/api/test_runtime.py:1-180`

**Interfaces:**
- Consumes: the four `LocalDashboardService` methods from Task 3.
- Produces: authenticated/no-store `/api/dashboard/overview`,
  `/api/dashboard/alerts`, `/api/dashboard/analytics/{24h|7d}` and
  `/api/dashboard/system`; closes the already-observed `/api/status` transport-exception
  detail without changing its healthy response.

- [x] **Step 1: Add API RED tests with a recording fake provider**

  Extend the existing `client()` helper with a `dashboard` keyword and add:

  ```python
  @dataclass
  class FakeDashboardService:
      calls: list[tuple[str, object]] = field(default_factory=list)

      def overview(self, now: datetime) -> DashboardOverviewV1:
          self.calls.append(("overview", now))
          return dashboard_overview(now)

      def alerts(self, now: datetime) -> DashboardAlertListV1:
          self.calls.append(("alerts", now))
          return dashboard_alert_list(now)

      def analytics(
          self, window: DashboardWindow, now: datetime
      ) -> DashboardAnalyticsV1:
          self.calls.append(("analytics", window))
          return dashboard_analytics(window, now)

      def system(self, now: datetime) -> DashboardSystemV1:
          self.calls.append(("system", now))
          return dashboard_system(now)
  ```

  Parameterize the four routes and assert unauthenticated requests return 401 with zero
  calls. Authenticated requests return 200, no-store and exactly the closed model keys.
  Assert `/api/dashboard/analytics/30d` returns 422 before provider access. With no
  provider, all four routes return only `{"detail":"DASHBOARD_DATA_UNAVAILABLE"}` and
  never reveal an exception. Make a fake method raise `DashboardServiceUnavailable` and
  assert the same stable 503 body. Check `Cache-Control: no-store` on 401, 422 and both
  503 paths as well as on 200.

- [x] **Step 2: Run API tests and observe RED**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q \
    tests/api/test_alpha_app.py -k 'dashboard and (overview or alerts or analytics or system)'
  ```

  Expected: route requests return 404 or the helper rejects the unknown runtime field.

- [x] **Step 3: Add one runtime protocol/field and four routes**

  In `apps/api/alpha.py`, define an `AlphaDashboard` protocol with the four exact method
  signatures, add `dashboard: AlphaDashboard | None = None` to `AlphaRuntime`, and a
  local accessor:

  ```python
  def dashboard_service() -> AlphaDashboard:
      if runtime.dashboard is None:
          raise HTTPException(
              status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
              detail="DASHBOARD_DATA_UNAVAILABLE",
          )
      return runtime.dashboard
  ```

  Each route depends on `require_parent`, calls the method with one `datetime.now(UTC)`,
  passes the validated model through `jsonable_encoder`, and catches only
  `DashboardServiceUnavailable`, mapping it to the same stable 503 with `raise ... from
  None`. Type the path parameter as `Literal["24h", "7d"]` and convert it with
  `DashboardWindow(window)`.

  Add one narrow HTTP middleware that sets `Cache-Control: no-store` after `call_next`
  for paths under `/api/dashboard/` and the fixed new Dashboard asset paths
  (`dashboard.css`, `dashboard-views.js`, `dashboard-analytics.js`,
  `dashboard-shell.js`). This is required because dependency 401s and FastAPI-generated
  422s occur before a route can add response headers. Do not change cache behavior for
  unrelated routes. Successful routes still return explicit `JSONResponse` objects with
  no-store, so the policy remains visible at each endpoint.

- [x] **Step 4: Add runtime wiring RED test**

  Monkeypatch `GuardianDashboardQuery` and `LocalDashboardService` with recording
  factories. Load a settings file whose relative `app.data_dir` is `relative-runtime`.
  Assert the Guardian query receives exactly
  `tmp_path / "relative-runtime" / "events.sqlite3"`; the aggregate receives the
  already-built environment service, the existing gateway and
  `camera_reply_enabled=False`, plus `timezone_name="Asia/Shanghai"`. Also assert no
  settings path still produces a Dashboard
  service with `guardian=None` and `environment=None`, so camera/system status degrades
  honestly instead of removing the UI.

  Add a separate gateway regression: make `urlopen` raise
  `OSError("private transport detail")` and assert `Go2RTCAlphaGateway.status()` retains
  the existing `camera`, `stream` and `detail` keys but sets detail to the fixed
  `camera_status_unavailable` code. Assert neither `OSError` nor the exception message is
  present. Preserve the current successful response exactly, including its existing
  stream fields, to avoid turning this privacy fix into an API redesign.

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_runtime.py \
    -k 'dashboard or gateway_status_failure_uses_stable_public_code'
  ```

  Expected: the Dashboard recording factories have not been called and the failure
  detail still contains the exception type.

- [x] **Step 5: Wire the production service without constructing a writable store**

  Import `GuardianDashboardQuery` and `LocalDashboardService` in `apps/api/runtime.py`.
  Preserve a nullable `settings` variable. When settings load, resolve `data_dir` once
  using the existing rule and construct the read-only Guardian query from
  `data_dir / "events.sqlite3"`. Build exactly one aggregate after the settings block:

  ```python
  dashboard = LocalDashboardService(
      camera=gateway,
      guardian=dashboard_guardian,
      environment=environment,
      camera_reply_enabled=(settings.voice_care.camera_reply_enabled if settings else False),
      timezone_name=(settings.app.timezone if settings else "Asia/Shanghai"),
  )
  ```

  Pass `dashboard=dashboard` to `AlphaRuntime`. Do not instantiate `EnvironmentStore`
  here; the existing environment bootstrap remains its sole owner.

  In the already-touched `Go2RTCAlphaGateway.status()` failure branch, replace
  `type(exc).__name__` with `camera_status_unavailable` and do not otherwise change the
  legacy status shape. The new Dashboard projection still ignores `detail`, `stream` and
  `known_streams` completely.

- [x] **Step 6: Run Task 4 GREEN and full API/runtime regression**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q \
    tests/api/test_alpha_app.py \
    tests/api/test_runtime.py \
    tests/dashboard
  ./.venv-alpha/bin/python -m compileall -q apps/api services/dashboard
  git diff --check
  ```

- [x] **Step 7: Commit Task 4**

  ```bash
  git add apps/api/alpha.py apps/api/runtime.py \
    tests/api/test_alpha_app.py tests/api/test_runtime.py
  git commit -m "feat: expose authenticated dashboard data APIs"
  ```

### Task 5: Replace the long page with semantic four-tab HTML and compact CSS

**Files:**
- Create: `apps/api/dashboard.css`
- Modify: `apps/api/alpha.py:193-326,357-420`
- Modify: `tests/api/test_alpha_app.py:280-415`

**Interfaces:**
- Consumes: existing fixed IDs required by `dashboard_viewer.js`, `hd_player.js` and
  `gauge_calibration.js`.
- Produces: semantic panel IDs `dashboard-overview`, `dashboard-alerts`,
  `dashboard-analytics`, `dashboard-system` and protected `/assets/dashboard.css`.

- [x] **Step 1: Write structural and CSS asset RED tests**

  Add assertions that the authenticated HTML contains one `role="tablist"`, four tabs,
  four matching panels, default overview selection, one live MJPEG source and the existing
  viewer IDs. Assert the old raw status `<pre id="status">` is absent. Test CSS without
  auth is 401; with auth it is `text/css`, no-store and contains the mobile breakpoint,
  visible focus rule and reduced-motion rule.

  ```python
  assert response.text.count('role="tab"') == 4
  assert response.text.count('role="tabpanel"') == 4
  assert 'id="tab-overview"' in response.text
  assert 'aria-selected="true"' in overview_button(response.text)
  assert response.text.count('src="/live.mjpeg"') == 1
  assert 'id="media-plane"' in response.text
  assert 'id="status"' not in response.text
  assert 'href="/assets/dashboard.css"' in response.text
  ```

- [x] **Step 2: Run HTML/CSS tests and observe RED**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py \
    -k 'dashboard or css or viewer'
  ```

  Expected: new tab IDs and CSS asset are absent.

- [x] **Step 3: Write the semantic HTML shell while preserving media IDs**

  Replace only `_DASHBOARD`. Keep `<img id="live-image" src="/live.mjpeg">`,
  `<video id="hd-video">`, `viewer`, `media-plane`, zoom/fullscreen/PTZ status,
  `snapshot-link`, `notify` and `gauge-calibration` IDs exactly once.

  Remove `refreshStatus()`, its startup call and its interval in the same edit that
  removes `<pre id="status">`; assert none of those strings remain so the intermediate
  page cannot dereference a deleted node or render raw `/api/status` JSON. Keep only the
  existing bounded test-notification click handler until Task 7 moves it into the shell.

  The new high-level structure is exact:

  ```html
  <main class="dashboard-shell">
    <header class="dashboard-header">
      <h1>Baby Monitor Local</h1>
      <p id="dashboard-health" role="status">正在读取本地监控状态…</p>
    </header>
    <nav class="dashboard-tabs" role="tablist" aria-label="监控页面">
      <button id="tab-overview" type="button" role="tab" tabindex="0" aria-controls="dashboard-overview" aria-selected="true">总览</button>
      <button id="tab-alerts" type="button" role="tab" tabindex="-1" aria-controls="dashboard-alerts" aria-selected="false">警报 <span id="alert-count" hidden></span></button>
      <button id="tab-analytics" type="button" role="tab" tabindex="-1" aria-controls="dashboard-analytics" aria-selected="false">数据</button>
      <button id="tab-system" type="button" role="tab" tabindex="-1" aria-controls="dashboard-system" aria-selected="false">系统</button>
    </nav>
    <section id="global-attention" role="status" hidden></section>
    <section id="dashboard-overview" role="tabpanel" aria-labelledby="tab-overview"></section>
    <section id="dashboard-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden></section>
    <section id="dashboard-analytics" role="tabpanel" aria-labelledby="tab-analytics" hidden></section>
    <section id="dashboard-system" role="tabpanel" aria-labelledby="tab-system" hidden></section>
  </main>
  ```

  Inside overview, place the existing viewer beside `overview-environment`,
  `overview-guardian`, `overview-components`, `overview-recent` and
  `overview-updated`/`overview-stale`. Alerts contains source buttons with
  `data-alert-source="all|guardian|environment|system"`, state buttons with
  `data-alert-state="all|open|recovered"`, plus `alerts-list`,
  `alerts-updated`/`alerts-stale` and a
  visually hidden `alerts-announcement` node with `aria-live="polite"`. Mark the initial
  `all` buttons with `aria-pressed="true"` and every other filter with false.
  Analytics contains the two window buttons, `analytics-refresh`, four
  KPI nodes, `analytics-trend`, `analytics-summary`, `analytics-table` and
  `analytics-updated`/`analytics-stale`; use `aria-pressed` on the two window buttons.
  System contains `system-components`, `system-updated`/`system-stale`,
  `system-refresh` and the existing maintenance controls.

- [x] **Step 4: Add compact local CSS and protected asset route**

  Use these fixed layout tokens, then cover every state class referenced by the HTML or
  upcoming presenters:

  ```css
  :root {
    color-scheme: dark;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    --page: #0b0d12;
    --surface: #151922;
    --surface-strong: #1c2230;
    --border: #2a3242;
    --text: #f4f7fb;
    --muted: #9aa6b8;
    --critical: #ff6b6b;
    --warning: #f2bd5a;
    --info: #66a7ff;
    --healthy: #4ed6a0;
  }

  .dashboard-shell { width: min(1180px, 100%); margin: 0 auto; padding: 12px; }
  .overview-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(250px, 1fr); gap: 10px; }
  .dashboard-tabs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); }
  button, a.button { min-height: 44px; }
  :focus-visible { outline: 3px solid #74b9ff; outline-offset: 2px; }
  [hidden] { display: none !important; }
  @media (max-width: 720px) {
    .dashboard-shell { padding: 8px; }
    .overview-grid { grid-template-columns: 1fr; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
  }
  ```

  Preserve the existing viewer transform, fullscreen, touch-action, HD layer and control
  rules. Add `.priority-critical`, `.priority-warning`, `.priority-info`, `.is-stale`,
  `.is-open`, `.is-recovered`, `.component-*`, compact card/list/grid/chart rules, and
  an `overflow-wrap:anywhere` rule for event IDs. Add a standard clipped
  `.visually-hidden` utility that remains available to assistive technology. Do not use
  color alone: each state row includes a visible text chip. Style the last-valid
  environment line with muted secondary size/color and no current-state class so it
  cannot visually masquerade as the current reading.

  Add `_DASHBOARD_STYLE = Path(__file__).with_name("dashboard.css")` and a protected
  `/assets/dashboard.css` route with `media_type="text/css"` and no-store.

- [x] **Step 5: Run Task 5 GREEN and viewer structure regression**

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py
  node --test tests/frontend/dashboard_viewer.test.mjs \
    tests/frontend/hd_player.test.mjs \
    tests/frontend/gauge_calibration.test.mjs
  git diff --check
  ```

- [x] **Step 6: Commit Task 5**

  ```bash
  git add apps/api/alpha.py apps/api/dashboard.css tests/api/test_alpha_app.py
  git commit -m "feat: add compact four tab dashboard shell"
  ```

### Task 6: Render closed overview, alert and system views

**Files:**
- Create: `apps/api/dashboard_views.js`
- Create: `tests/frontend/dashboard_views.test.mjs`
- Modify: `apps/api/alpha.py:193-200,364-420`
- Modify: `tests/api/test_alpha_app.py:360-430`

**Interfaces:**
- Consumes: JSON forms of `DashboardOverviewV1`, `DashboardAlertListV1` and
  `DashboardSystemV1`.
- Produces: global `BabyMonitorDashboardViews` with `presentOverview`, `presentAlerts`,
  `presentSystem`, `filterAlerts`, `applyAlertFilters`, `renderOverview`,
  `renderAlerts`, `renderSystem`, `markStale` and `markUnavailable`.

- [x] **Step 1: Write presenter and safe-DOM RED tests**

  Follow the existing UMD test style and fake elements. Cover closed-key rejection,
  last-valid separation, priority labels and no `innerHTML` writes:

  ```javascript
  test("unavailable current never becomes the main reading", () => {
    const view = presentOverview(overviewPayload({
      environment: {
        state: "unavailable",
        temperature_c: null,
        humidity_rh: null,
        captured_at: null,
        fresh_until: null,
        failure_reason: "environment_no_reading",
        last_valid_temperature_c: 22,
        last_valid_humidity_rh: 48,
        last_valid_captured_at: "2026-09-03T00:55:00Z",
      },
    }));
    assert.equal(view.environment.currentText, "不可用");
    assert.equal(view.environment.lastValidText, "22.0°C · 48.0%RH");
    assert.doesNotMatch(view.environment.currentText, /22/);
  });

  test("unknown candidate alert is rejected instead of shown as confirmed", () => {
    assert.throws(
      () => presentAlerts(alertPayload([{...alert(), kind: "watch_candidate"}])),
      /closed dashboard alert/,
    );
  });
  ```

  Add a malicious event ID containing HTML syntax and assert the fake element receives
  it only through `textContent`. Add mapping assertions for every closed alert kind,
  evidence state, notification state, resolution cause, component state and reason code.
  Add source/state filter tests proving `all`, `guardian`, `environment`, `system`,
  `open` and `recovered` are the only accepted values and that filtering never changes
  the server order.

- [x] **Step 2: Run view tests and observe RED**

  ```bash
  node --test tests/frontend/dashboard_views.test.mjs
  ```

  Expected: module-not-found failure.

- [x] **Step 3: Implement strict UMD presenters**

  Use the established wrapper:

  ```javascript
  (function exposeDashboardViews(root, factory) {
    "use strict";
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    root.BabyMonitorDashboardViews = api;
  })(globalThis, function createDashboardViewsApi() {
    "use strict";
    const sourceLabels = new Map([
      ["guardian", "Guardian"],
      ["environment", "环境"],
      ["system", "系统"],
    ]);
    const priorityLabels = new Map([
      ["critical", "高风险"],
      ["warning", "需检查"],
      ["info", "信息"],
    ]);
    return {
      applyAlertFilters,
      filterAlerts,
      markStale,
      markUnavailable,
      presentAlerts,
      presentOverview,
      presentSystem,
      renderAlerts,
      renderOverview,
      renderSystem,
    };
  });
  ```

  Validate the exact top-level keys and alert keys before presenting. Use closed Maps for
  Chinese labels; a missing map entry throws `TypeError("closed dashboard alert required")`.
  Render rows with `document.createElement`, `textContent`, `className`, `dataset` and
  `setAttribute` only. Never assign `innerHTML` or insert server-provided CSS classes.

  `renderOverview` updates the global attention, count badge, environment, Guardian
  counts, components, recent list, `dashboard-health` and the localized generated time.
  When attention exists, render one button with the
  trusted stable ID in `data-alert-target`; when absent, clear and hide the region.
  `renderAlerts` replaces list children, stores the stable alert ID in `data-alert-id`,
  and highlights only an exact hash-requested ID.
  Render nullable Guardian counts as “不可用” and numeric zero as `0`; never collapse the
  two states through a truthiness check.
  The header summary precedence is confirmed critical alert, warning/degraded/unavailable
  component, then “当前未发现未恢复警报”; it may say healthy only when every returned
  required component is healthy or intentionally disabled.
  Render alert/system generated times through an injected `Intl.DateTimeFormat` too.
  `filterAlerts` accepts only the closed source/state values and returns a same-order
  subset; `applyAlertFilters` toggles existing rows through their trusted
  `data-alert-source` and `data-alert-state` attributes. `renderSystem` renders component,
  state label, reason label and localized update time.

- [x] **Step 4: Add and verify the protected view asset**

  Add `_DASHBOARD_VIEWS_SCRIPT`, its authenticated/no-store route, and an API test that
  verifies the response contains `BabyMonitorDashboardViews` but not media/path literals.

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py \
    -k 'dashboard and asset'
  node --test tests/frontend/dashboard_views.test.mjs
  git diff --check
  ```

- [x] **Step 5: Commit Task 6**

  ```bash
  git add apps/api/alpha.py apps/api/dashboard_views.js \
    tests/api/test_alpha_app.py tests/frontend/dashboard_views.test.mjs
  git commit -m "feat: render dashboard overview alerts and system"
  ```

### Task 7: Add accessible tabs, deep links and one refresh scheduler

**Files:**
- Create: `apps/api/dashboard_shell.js`
- Create: `tests/frontend/dashboard_shell.test.mjs`
- Modify: `apps/api/alpha.py:193-200,300-326,364-430`
- Modify: `tests/api/test_alpha_app.py:300-430`

**Interfaces:**
- Consumes: `BabyMonitorDashboardViews`, browser fetch/timer/history primitives, and an
  analytics controller exposing `activate()`.
- Produces: `BabyMonitorDashboardShell` with `parseDashboardHash`, `selectTab`,
  `createResourceController` and `mountDashboardShell`.

- [x] **Step 1: Write tab/hash RED tests**

  Test the exact mappings:

  ```javascript
  assert.deepEqual(parseDashboardHash("#tab=alerts&alert=guardian:event-1"), {
    tab: "alerts",
    alertId: "guardian:event-1",
    environmentIncidentId: null,
  });
  assert.deepEqual(parseDashboardHash("#environment-incident=incident-1"), {
    tab: "alerts",
    alertId: "environment:incident-1",
    environmentIncidentId: "incident-1",
  });
  assert.deepEqual(parseDashboardHash("#tab=unknown"), {
    tab: "overview",
    alertId: null,
    environmentIncidentId: null,
  });
  ```

  Mount a four-tab fake DOM and prove click, ArrowLeft/ArrowRight, Home and End update
  `aria-selected`, roving `tabIndex`, panel `hidden`, focus and the hash. Selecting a Tab
  must leave the same `live-image` object in the document.

- [x] **Step 2: Write scheduler RED tests**

  Use deferred promises to prove:

  - mount immediately requests overview, alerts and system exactly once;
  - exactly one 15,000ms interval is registered;
  - an interval tick while a resource request is pending does not start a duplicate;
  - a late generation cannot replace a newer response;
  - first failure calls `markUnavailable`; later failure retains the rendered object and
    calls `markStale` with the prior success time;
  - unchanged alerts do not cause a second `aria-live` announcement (the comparison
    ignores top-level generation/display timestamps but includes IDs, state, priority,
    reasons, evidence and notification state);
  - analytics `activate()` is called on first selection and not by 15-second ticks;
  - `pagehide` clears one timer and BFCache `pageshow` restores one timer;
  - `visibilitychange` clears the timer while hidden and immediately refreshes plus
    restores exactly one timer when visible.

  Click the rendered global-attention button and assert the shell selects `alerts`, writes
  the encoded stable alert hash, then focuses/highlights only its exact row. Click each
  source/state filter and `system-refresh`; prove filters do not fetch, survive the next
  render and the manual control requests only `/api/dashboard/system`.

- [x] **Step 3: Run shell tests and observe RED**

  ```bash
  node --test tests/frontend/dashboard_shell.test.mjs
  ```

  Expected: module-not-found failure.

- [x] **Step 4: Implement closed hash parsing and accessible selection**

  Decode only `tab`, `alert` and the legacy `environment-incident` key. Catch malformed
  percent encoding and return overview. Bound a new alert ID to 160 characters and a
  legacy incident ID to the existing 128-character `_INCIDENT_ID` alphabet; invalid IDs
  are ignored and never become paths. Accept Tab values only from this fixed map:

  ```javascript
  const tabs = new Map([
    ["overview", "dashboard-overview"],
    ["alerts", "dashboard-alerts"],
    ["analytics", "dashboard-analytics"],
    ["system", "dashboard-system"],
  ]);
  ```

  `selectTab` updates all four controls/panels, focuses only for keyboard navigation,
  writes `#tab=<name>` with `history.replaceState`, and calls analytics activation only
  for `analytics`. For a legacy incident, retain the old hash until the matching alert
  is rendered, then focus/highlight without sending the ID to a server path. Use the same
  pending-target mechanism for `#tab=alerts&alert=<id>` and attention-button clicks so a
  slower alerts response cannot lose the requested focus.

- [x] **Step 5: Implement a generation-safe resource controller and shared scheduler**

  Use one controller per URL with these state fields:

  ```javascript
  const state = {
    generation: 0,
    inFlight: null,
    lastPayload: null,
    lastSuccessAt: null,
  };
  ```

  `refresh()` returns the current promise when `inFlight` exists. Otherwise increment
  generation, fetch the fixed URL, require `response.ok`, validate/render through the
  injected view method, and update last success only if the generation remains current.
  On failure, expose only `DASHBOARD_DATA_UNAVAILABLE`; never copy `error.message`.
  `mountDashboardShell` creates controllers for the three fixed endpoints and one
  interval that invokes them. It never selects a stream, rebuilds media DOM or starts
  analytics refresh.

  Compare a closed semantic signature rather than the whole alert response before
  updating the polite live-region text, so a new `generated_at` alone is silent. Pause
  the shared interval on `pagehide` or while `document.hidden`; on persisted `pageshow`
  or a transition back to visible, perform one refresh and install one interval only if
  none exists. Do not touch the media lifecycle handlers owned by the existing viewer and
  HD modules.

  Shell owns `sourceFilter="all"` and `stateFilter="all"`. Clicks on the fixed
  `data-alert-source` and `data-alert-state` buttons update `aria-pressed` and call
  `views.applyAlertFilters`; they do not refetch or construct a URL. Preserve selected
  filters across 15-second alert renders. The `system-refresh` button invokes only the
  system resource controller.

- [x] **Step 6: Add the protected shell asset and load it after its dependencies**

  Add the route and include scripts in this order:

  ```html
  <script defer src="/assets/hd-player.js"></script>
  <script defer src="/assets/dashboard-viewer.js"></script>
  <script defer src="/assets/gauge-calibration.js"></script>
  <script defer src="/assets/dashboard-views.js"></script>
  <script defer src="/assets/dashboard-shell.js"></script>
  ```

  Remove the remaining inline test-notification script and the old auto-mounting
  `guardian-events.js` and `environment-dashboard.js` script tags (the raw status poll
  was already removed in Task 5). Keep their asset routes unchanged. Move the existing
  test-notification click handler into shell code;
  it posts only to fixed `/api/test-notification` and presents a closed success/failure
  phrase.

- [x] **Step 7: Run Task 7 GREEN and media lifecycle regression**

  ```bash
  node --test \
    tests/frontend/dashboard_shell.test.mjs \
    tests/frontend/dashboard_views.test.mjs \
    tests/frontend/dashboard_viewer.test.mjs \
    tests/frontend/hd_player.test.mjs \
    tests/frontend/gauge_calibration.test.mjs
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py
  git diff --check
  ```

- [x] **Step 8: Commit Task 7**

  ```bash
  git add apps/api/alpha.py apps/api/dashboard_shell.js \
    tests/api/test_alpha_app.py tests/frontend/dashboard_shell.test.mjs
  git commit -m "feat: orchestrate dashboard tabs and refresh"
  ```

### Task 8: Add lazy analytics presentation and gap-preserving charts

**Files:**
- Create: `apps/api/dashboard_analytics.js`
- Create: `tests/frontend/dashboard_analytics.test.mjs`
- Modify: `apps/api/alpha.py:193-200,300-326,364-440`
- Modify: `tests/api/test_alpha_app.py:300-450`
- Modify: `tests/frontend/dashboard_shell.test.mjs`

**Interfaces:**
- Consumes: `/api/dashboard/analytics/24h` and `/api/dashboard/analytics/7d`.
- Produces: `BabyMonitorDashboardAnalytics` with `analyticsPath`, `presentAnalytics`,
  `drawAnalyticsTrend`, and `mountDashboardAnalytics`; the mounted controller exposes
  `activate()`, `refresh()` and `selectWindow(windowName)`.

- [x] **Step 1: Write closed path and metric RED tests**

  ```javascript
  assert.equal(analyticsPath("24h"), "/api/dashboard/analytics/24h");
  assert.equal(analyticsPath("7d"), "/api/dashboard/analytics/7d");
  assert.throws(() => analyticsPath("30d"), /closed analytics window/);

  const view = presentAnalytics(analyticsPayload({
    environment: {
      state: "available",
      sample_count: 0,
      available_count: 0,
      availability_rate: null,
      incident_counts: {range_normal: 0, range_critical: 0, unreadable: 0},
      buckets: [],
    },
  }));
  assert.equal(view.availabilityText, "无数据");
  assert.equal(view.notificationSuccessText, "无数据");
  ```

  Assert event count `0` renders as `0`, not “无数据”; median seconds render as bounded
  minutes/seconds; evidence label includes both retained denominator and missing count;
  timestamps use an injected `Intl.DateTimeFormat` for deterministic tests. Add an
  unavailable Guardian section whose stored counts are zero and assert every Guardian
  KPI says “不可用”, plus the symmetrical environment case; source failure must not be
  presented as a real zero.

- [x] **Step 2: Write chart and lazy-loading RED tests**

  Provide three buckets with a null middle bucket. Record Canvas calls and assert each
  series begins a new subpath after the gap rather than drawing across it. Assert:

  - mount performs zero fetches;
  - first `activate()` fetches 24h once;
  - a second activation reuses the successful payload;
  - selecting 7d fetches the closed 7d path once;
  - manual refresh fetches the current window again;
  - failed refresh retains previous metrics/chart and marks stale;
  - a pending request is not duplicated.

- [x] **Step 3: Run analytics tests and observe RED**

  ```bash
  node --test tests/frontend/dashboard_analytics.test.mjs
  ```

  Expected: module-not-found failure.

- [x] **Step 4: Implement strict presentation and Canvas drawing**

  Use a UMD wrapper without auto-fetch. Validate exact top-level and section fields.
  `drawAnalyticsTrend` clears the canvas, draws axes, and for each temperature/humidity
  field resets `drawing=false` on `null`; the next numeric point uses `moveTo`, not
  `lineTo`. Scale temperature and humidity independently using their available finite
  values, with a minimum non-zero range. If no finite values exist, draw no line and
  leave the textual summary visible.

  Render four KPIs, risk composition, incident composition, retained evidence state,
  notification delivered/rejected/pending counts and a real HTML table of bucket start,
  availability, temperature median and humidity median. Cap rendered rows to the response
  bound and use `textContent` for every cell.

- [x] **Step 5: Implement lazy controller and integrate with the shell**

  `mountDashboardAnalytics(environment)` owns `currentWindow="24h"`, one cached payload
  per window, one in-flight promise per window and generation numbers. `activate()` loads
  only when the current window has no successful payload. `selectWindow` accepts the
  closed values, updates `aria-pressed`, renders cached data or fetches once. `refresh`
  always requests the active window unless its request is already pending.
  Every successful render updates `analytics-updated` from the response `generated_at`;
  a failed refresh retains that value and adds the last-success stale message.

  Load `/assets/dashboard-analytics.js` after `dashboard-views.js` and before
  `dashboard-shell.js`. On mount, shell creates the analytics controller and passes it to
  tab selection. Add one API test for auth/no-store and one shell test proving analytics
  is not part of the interval refresh.

- [x] **Step 6: Run Task 8 GREEN and every frontend test**

  ```bash
  node --test tests/frontend/*.test.mjs
  ./.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py tests/dashboard
  git diff --check
  ```

  Expected: all old 73 frontend tests plus the new Dashboard tests pass; report the exact
  new total from Node output rather than copying an estimate into evidence.

- [x] **Step 7: Commit Task 8**

  ```bash
  git add apps/api/alpha.py apps/api/dashboard_analytics.js \
    tests/api/test_alpha_app.py tests/frontend/dashboard_analytics.test.mjs \
    tests/frontend/dashboard_shell.test.mjs
  git commit -m "feat: add bounded dashboard analytics views"
  ```

### Task 9: Close compatibility, privacy and integration-ready evidence

**Files:**
- Modify: `tests/api/test_alpha_app.py`
- Modify: `tests/api/test_runtime.py`
- Modify: `tests/frontend/dashboard_shell.test.mjs`
- Modify: `docs/superpowers/plans/2026-09-03-dashboard-tabs-analytics-alerts.md`
- Create: `docs/reviews/2026-09-03-dashboard-tabs-analytics-alerts-review.md`

**Interfaces:**
- Consumes: all previous task outputs and the existing Viewer, Environment, Guardian,
  calibration and HD compatibility suites.
- Produces: fresh aggregate software evidence and a merge-ready, no-push handoff.

- [x] **Step 1: Add final cross-boundary regression tests and require GREEN**

  Add exact tests that were not owned by a single component:

  - every new API and asset authenticates before service/file access and has no-store;
  - HTML has one live source, four tabs, no raw status `<pre>`, no external `http://` or
    `https://` resource, no old auto-mounting script tag and correct local script order;
  - the old `/incidents/incident-1` 303 target remains unchanged;
  - a legacy incident hash selects and highlights only `environment:incident-1`;
  - provider failure responses contain only stable public codes and no `sqlite`, path,
    exception class, stream list, token, topic, confidence, rule version or evidence key;
  - the test-notification, snapshot, HD ticket, PTZ-disabled and calibration endpoints
    retain their existing tests and behavior;
  - a 320px/390px static layout contract finds the max-720 media query, four equal tabs,
    44px targets and no fixed page width wider than the viewport.

  Run the focused gate. These tests are expected to be GREEN after Tasks 1–8. If one is
  RED, keep its output, stop Task 9, return to the owning earlier task, add the narrow
  regression/fix there and commit it with that task's exact production files before
  restarting this gate; do not hide an unplanned source fix in the review commit.

  ```bash
  ./.venv-alpha/bin/python -m pytest -q tests/dashboard tests/api/test_alpha_app.py tests/api/test_runtime.py
  node --test tests/frontend/*.test.mjs
  ```

- [x] **Step 2: Run compilation and the full software gate**

  The pre-integration executor-policy exception is retained in the review record as
  historical evidence. After integration, the exact merged head was rerun in a macOS
  execution context that permits Unix-domain socket fixtures: full Python returned
  zero with `2497 passed` and one expected public-corpus skip, frontend returned zero
  with `132 passed`, and compilation plus `git diff --check` returned zero. The prior
  AF_UNIX failure did not reproduce.

  ```bash
  ./.venv-alpha/bin/python -m compileall -q apps packages services tools
  ./.venv-alpha/bin/python -m pytest -q
  node --test tests/frontend/*.test.mjs
  git diff --check
  ```

  All four commands must return zero. A missing interpreter/dependency is BLOCKED, not a
  pass and not permission to skip Python evidence.

- [x] **Step 3: Scan the tracked branch delta for private or unrelated material**

  ```bash
  git diff --name-status cabd4cf10e35a4aa9877a9b3c9a1e8692818948d..HEAD
  git diff --check cabd4cf10e35a4aa9877a9b3c9a1e8692818948d..HEAD
  if git diff --unified=0 cabd4cf10e35a4aa9877a9b3c9a1e8692818948d..HEAD -- \
      services/dashboard services/environment/dashboard.py services/storage/environment.py \
      apps/api tests/dashboard tests/environment/test_dashboard.py \
      tests/storage/test_environment_store.py tests/api tests/frontend \
    | rg -n '^\+[^+].*(github_pat_|BEGIN (RSA|OPENSSH|PRIVATE)|/Users/|NTFY_TOKEN=|MI_[A-Z_]*=)'; then
    exit 1
  fi
  git status --short
  ```

  Expected: only planned source/tests/docs, no secret or private-path match, and no
  untracked runtime media, database, settings or generated artifact. If the scan matches
  a deliberate test-only sentinel, inspect it and narrow the sentinel without weakening
  the production scan before rerunning; do not declare a command that exited non-zero
  clean.

- [x] **Step 4: Perform a read-only future-merge preview**

  ```bash
  git fetch origin
  git for-each-ref --format='%(refname:short)' refs/remotes/origin/codex/ | sort
  base=$(git merge-base HEAD origin/codex/visual-regression-corpus)
  git log --left-right --cherry-pick --oneline "$base"...HEAD
  git log --left-right --cherry-pick --oneline "$base"...origin/codex/visual-regression-corpus
  git merge-tree "$base" HEAD origin/codex/visual-regression-corpus > /tmp/dashboard-merge-tree.txt
  rg -n '^(<<<<<<<|=======|>>>>>>>)' /tmp/dashboard-merge-tree.txt || true
  ```

  This is inspection only. Do not run `git merge`, `git rebase`, `git cherry-pick` or
  `git push`. The listed Codex refs are inventory, not permission to choose or combine a
  second target automatically. Record whether the known target advanced and list exact
  conflict paths, especially `apps/api/alpha.py`, `apps/api/runtime.py` and global handoff
  documents. If the owner later names a different Codex integration ref, repeat the same
  merge-base/log/merge-tree preview against that exact ref before any integration action.

- [x] **Step 5: Write the bounded review record**

  Create `docs/reviews/2026-09-03-dashboard-tabs-analytics-alerts-review.md` with:

  - branch, base and exact implementation HEAD;
  - task-by-task commit list;
  - exact focused/full Python and Node commands with pass counts;
  - compile and diff results;
  - proof that no real camera, household media, notification or database write ran;
  - responsive/accessibility behaviors proven by software and the remaining real iPhone
    visual smoke gate;
  - target branch merge-base, advance state and conflict paths;
  - explicit evidence-commit-time flags: `owner_exception_accepted=true`,
    `push_authorized=true`, `push_performed=false`, `pr=false`,
    `merge_performed=false`, `main_changed=false`, `stable_changed=false`.

  Mark all completed plan checkboxes only after their evidence exists. A non-zero Python
  gate remains non-green. If the owner explicitly accepts a documented infrastructure
  exception, record that acceptance without checking the exact full-Python-zero step.

- [x] **Step 6: Commit the accepted-exception handoff**

  ```bash
  git add tests/api/test_alpha_app.py tests/api/test_runtime.py \
    tests/frontend/dashboard_shell.test.mjs \
    docs/superpowers/plans/2026-09-03-dashboard-tabs-analytics-alerts.md \
    docs/reviews/2026-09-03-dashboard-tabs-analytics-alerts-review.md
  git diff --cached --check
  git commit -m "docs: record dashboard integration evidence"
  ```

  Do not update `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md` or `docs/NEXT.md`
  from their stale feature-branch snapshots. Reconcile those high-conflict files in a
  separate owner-approved integration-doc commit after the actual target branch and
  merge order are known.

## Completion handoff

Report:

- four-tab behavior and API/data contracts delivered;
- exact files and commit IDs;
- focused/full Python and Node pass counts;
- privacy and read-only evidence;
- what software testing does not prove about household accuracy or real devices;
- current branch/HEAD, target merge-base and conflict preview;
- explicit remote state and confirmation that nothing was pushed, merged or rebased;
- the next action: owner chooses integration target and separately authorizes push or
  merge after reviewing the evidence.
