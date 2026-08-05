from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from packages.contracts.events import EnvironmentSourceKind
from packages.contracts.settings import AppSettings
from services.environment.dashboard import LocalEnvironmentDashboardService
from services.events.environment_pipeline import EnvironmentPipelineSink
from services.events.environment_state import EnvironmentStatePolicy
from services.gauge.calibration import GaugeCalibrationStore
from services.gauge.reader import Ws2021Reader
from services.gauge.source import Ws2021GaugeSource
from services.gauge.worker import GaugeWorker
from services.notifications.ntfy import NtfyEnvironmentNotifier, TrustedDashboardLink
from services.storage.environment import EnvironmentStore
from services.stream.frame_source import Go2RtcControlledFrameSource


def state_policy(settings: AppSettings) -> EnvironmentStatePolicy:
    thresholds = settings.thresholds
    environment = settings.environment
    return EnvironmentStatePolicy(
        temperature_low_c=thresholds.temperature_low_c,
        temperature_high_c=thresholds.temperature_high_c,
        temperature_critical_low_c=thresholds.temperature_critical_low_c,
        temperature_critical_high_c=thresholds.temperature_critical_high_c,
        humidity_low_rh=thresholds.humidity_low_rh,
        humidity_high_rh=thresholds.humidity_high_rh,
        humidity_critical_low_rh=thresholds.humidity_critical_low_rh,
        humidity_critical_high_rh=thresholds.humidity_critical_high_rh,
        normal_sustained_seconds=environment.normal_sustained_seconds,
        recovery_sustained_seconds=environment.recovery_sustained_seconds,
        unreadable_seconds=environment.unreadable_seconds,
        critical_confirmations=environment.critical_confirmations,
        critical_min_span_seconds=environment.critical_min_span_seconds,
    )


def _resolve(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else project_root / path


def environment_store(settings: AppSettings, project_root: Path) -> EnvironmentStore:
    data_dir = _resolve(project_root, settings.app.data_dir)
    return EnvironmentStore(data_dir / "environment.sqlite3")


def calibration_store(
    settings: AppSettings,
    project_root: Path,
) -> GaugeCalibrationStore:
    return GaugeCalibrationStore(
        _resolve(project_root, settings.environment.calibration_path)
    )


def build_dashboard_service(
    settings: AppSettings,
    project_root: Path,
) -> LocalEnvironmentDashboardService:
    return LocalEnvironmentDashboardService(
        store=environment_store(settings, project_root),
        calibration_store=calibration_store(settings, project_root),
        policy=state_policy(settings),
    )


def resolve_notification_topic(
    settings: AppSettings,
    environ: Mapping[str, str],
) -> str:
    topic = environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        topic = settings.notifications.ntfy_topic.strip()
    if topic == "replace-with-private-topic":
        raise ValueError("a private ntfy topic must be configured")
    return topic


def build_gauge_worker(
    settings: AppSettings,
    project_root: Path,
    environ: Mapping[str, str],
) -> GaugeWorker:
    if settings.environment.source_kind is not EnvironmentSourceKind.WS2021_GAUGE:
        raise ValueError("environment source_kind is not implemented")
    store = environment_store(settings, project_root)
    notifier = None
    dashboard_url = environ.get("BABY_MONITOR_DASHBOARD_URL", "").strip()
    if dashboard_url:
        notifier = NtfyEnvironmentNotifier(
            ntfy_base_url=environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
            topic=resolve_notification_topic(settings, environ),
            token=environ.get(settings.notifications.ntfy_token_env) or None,
            dashboard_link=TrustedDashboardLink(url=dashboard_url),
        )
    sink = EnvironmentPipelineSink.restore(
        store=store,
        policy=state_policy(settings),
        notifier=notifier,
        retention_days=settings.retention.reading_retention_days,
    )
    base_url = (
        f"http://{settings.stream.go2rtc_api_host}:"
        f"{settings.stream.go2rtc_api_port}"
    )
    source = Ws2021GaugeSource(
        frame_source=Go2RtcControlledFrameSource(base_url=base_url),
        calibration_store=calibration_store(settings, project_root),
        reader=Ws2021Reader(
            minimum_confidence=settings.environment.minimum_confidence,
            freshness_seconds=settings.environment.freshness_seconds,
        ),
        burst_frames=settings.environment.burst_frames,
        burst_interval_ms=settings.environment.burst_interval_ms,
        freshness_seconds=settings.environment.freshness_seconds,
    )
    return GaugeWorker(
        source=source,
        sink=sink,
        interval_seconds=settings.environment.interval_seconds,
    )
