from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from services.dashboard.contracts import (
    DashboardAlertV1,
    DashboardAnalyticsV1,
    DashboardEnvironmentAnalyticsV1,
    DashboardEnvironmentCurrentV1,
    DashboardEnvironmentIncidentCountsV1,
    DashboardEvidenceCountsV1,
    DashboardNotificationCountsV1,
    DashboardTrendBucketV1,
    DashboardWindow,
)


NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


def alert_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
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
    values.update(overrides)
    return values


def test_alert_contract_rejects_extra_candidate_state_and_naive_time() -> None:
    values = alert_values()

    assert DashboardAlertV1(**values).state == "open"

    with pytest.raises(ValidationError):
        DashboardAlertV1(**values, candidate_state="watch")
    with pytest.raises(ValidationError):
        DashboardAlertV1(**{**values, "opened_at": NOW.replace(tzinfo=None)})


def test_recovered_alert_requires_ordered_recovery_and_open_alert_has_no_recovery() -> None:
    recovered = DashboardAlertV1(
        **alert_values(
            state="recovered",
            recovered_at=NOW + timedelta(minutes=1),
            updated_at=NOW + timedelta(minutes=1),
            resolution_cause="explicit_safe",
        )
    )

    assert recovered.recovered_at == NOW + timedelta(minutes=1)

    with pytest.raises(ValidationError):
        DashboardAlertV1(**alert_values(state="recovered"))
    with pytest.raises(ValidationError):
        DashboardAlertV1(
            **alert_values(
                state="recovered",
                recovered_at=NOW - timedelta(microseconds=1),
                resolution_cause="explicit_safe",
            )
        )
    with pytest.raises(ValidationError):
        DashboardAlertV1(**alert_values(recovered_at=NOW))


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


def test_unavailable_environment_analytics_cannot_report_incidents() -> None:
    with pytest.raises(ValidationError):
        DashboardEnvironmentAnalyticsV1(
            state="unavailable",
            sample_count=0,
            available_count=0,
            availability_rate=None,
            incident_counts=DashboardEnvironmentIncidentCountsV1(
                range_normal=1,
                range_critical=0,
                unreadable=0,
            ),
            buckets=(),
        )


def test_bucket_requires_derived_availability_and_complete_ordered_values() -> None:
    values = {
        "started_at": NOW,
        "ended_at": NOW + timedelta(minutes=5),
        "sample_count": 2,
        "available_count": 1,
        "availability_rate": 0.5,
        "temperature_min_c": 20.0,
        "temperature_median_c": 21.0,
        "temperature_max_c": 22.0,
        "humidity_min_rh": 40.0,
        "humidity_median_rh": 50.0,
        "humidity_max_rh": 60.0,
    }

    assert DashboardTrendBucketV1(**values).availability_rate == 0.5

    with pytest.raises(ValidationError):
        DashboardTrendBucketV1(**{**values, "availability_rate": 0.4})
    with pytest.raises(ValidationError):
        DashboardTrendBucketV1(**{**values, "temperature_median_c": None})


def test_aggregate_count_models_require_their_derived_totals_and_rates() -> None:
    evidence = DashboardEvidenceCountsV1(
        collecting=1,
        ready=2,
        failed=3,
        interrupted=4,
        retained_total=10,
        missing=5,
        ready_rate=0.2,
    )
    notifications = DashboardNotificationCountsV1(
        pending=1,
        delivered=3,
        rejected=1,
        terminal_total=4,
        success_rate=0.75,
    )

    assert evidence.retained_total == 10
    assert notifications.terminal_total == 4

    with pytest.raises(ValidationError):
        DashboardEvidenceCountsV1(**{**evidence.model_dump(), "ready_rate": 0.3})
    with pytest.raises(ValidationError):
        DashboardNotificationCountsV1(
            **{**notifications.model_dump(), "terminal_total": 3}
        )


def test_analytics_rejects_a_window_with_the_wrong_duration() -> None:
    environment = DashboardEnvironmentAnalyticsV1(
        state="unavailable",
        sample_count=0,
        available_count=0,
        availability_rate=None,
        incident_counts=DashboardEnvironmentIncidentCountsV1(
            range_normal=0,
            range_critical=0,
            unreadable=0,
        ),
        buckets=(),
    )

    with pytest.raises(ValidationError):
        DashboardAnalyticsV1(
            schema_version=1,
            generated_at=NOW,
            window=DashboardWindow.HOURS_24,
            started_at=NOW,
            ended_at=NOW + timedelta(hours=23),
            environment=environment,
            guardian={
                "state": "unavailable",
                "confirmed_count": 0,
                "recovered_count": 0,
                "intervention_count": 0,
                "recovery_median_seconds": None,
                "risk_counts": {
                    "face_not_visible": 0,
                    "prone_candidate": 0,
                    "outside_candidate": 0,
                },
                "evidence_counts": {
                    "collecting": 0,
                    "ready": 0,
                    "failed": 0,
                    "interrupted": 0,
                    "retained_total": 0,
                    "missing": 0,
                    "ready_rate": None,
                },
                "notification_counts": {
                    "pending": 0,
                    "delivered": 0,
                    "rejected": 0,
                    "terminal_total": 0,
                    "success_rate": None,
                },
            },
        )
