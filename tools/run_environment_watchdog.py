from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Mapping
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.environment.local_env import load_local_env_file
from services.environment.watchdog import EnvironmentWatchdog
from services.events.environment_state import EnvironmentStatePolicy
from services.notifications.ntfy import NtfyEnvironmentNotifier, TrustedDashboardLink
from services.storage.environment import EnvironmentStore


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the independent environment missing-record watchdog."
    )
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    return parser.parse_args(argv)


def policy_from_settings(settings: AppSettings | None) -> EnvironmentStatePolicy:
    if settings is None:
        return EnvironmentStatePolicy()
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


def notifier_from_env(
    settings: AppSettings | None,
    environ: Mapping[str, str],
) -> NtfyEnvironmentNotifier | None:
    dashboard_url = environ.get("BABY_MONITOR_DASHBOARD_URL", "").strip()
    topic = environ.get("NTFY_TOPIC", "").strip()
    if not topic and settings is not None:
        topic = settings.notifications.ntfy_topic.strip()
    if not dashboard_url or not topic or topic == "replace-with-private-topic":
        return None
    token_name = (
        settings.notifications.ntfy_token_env if settings is not None else "NTFY_TOKEN"
    )
    return NtfyEnvironmentNotifier(
        ntfy_base_url=environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
        topic=topic,
        token=environ.get(token_name) or None,
        dashboard_link=TrustedDashboardLink(url=dashboard_url),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_local_env_file(args.env_file)
    try:
        settings: AppSettings | None = AppSettings.load(args.settings)
    except Exception:
        settings = None
    if settings is not None and not settings.environment.enabled:
        return 0
    data_dir = (
        settings.app.data_dir if settings is not None else Path("runtime")
    )
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    watchdog = EnvironmentWatchdog(
        store=EnvironmentStore(data_dir / "environment.sqlite3"),
        policy=policy_from_settings(settings),
        notifier=notifier_from_env(settings, os.environ),
    )
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    watchdog.run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
