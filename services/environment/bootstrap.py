from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from packages.contracts.events import EnvironmentSourceKind
from packages.contracts.settings import AppSettings
from services.environment.dashboard import LocalEnvironmentDashboardService
from services.events.environment_state import EnvironmentStatePolicy
from services.gauge.calibration import GaugeCalibrationStore
from services.gauge.locator import GaugeLocator, OpenVinoGaugeBackend
from services.gauge.reader import Ws2021Reader
from services.gauge.source import Ws2021GaugeSource
from services.gauge.worker import GaugeWorker
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


def build_gauge_worker(
    settings: AppSettings,
    project_root: Path,
    environ: Mapping[str, str],
) -> GaugeWorker:
    if settings.environment.source_kind is not EnvironmentSourceKind.WS2021_GAUGE:
        raise ValueError("environment source_kind is not implemented")
    store = environment_store(settings, project_root)
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
        locator=(
            GaugeLocator(
                backend=OpenVinoGaugeBackend(
                    model_path=_resolve(
                        project_root,
                        settings.environment.localization_model_path,
                    ),
                    metadata_path=_resolve(
                        project_root,
                        settings.environment.localization_model_path,
                    ).with_name("metadata.json"),
                )
            )
            if settings.environment.auto_localization
            else None
        ),
    )
    return GaugeWorker(
        source=source,
        sink=store,
        interval_seconds=settings.environment.interval_seconds,
    )
