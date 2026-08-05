from __future__ import annotations

from collections.abc import Mapping

from packages.contracts.settings import AppSettings
from services.notifications.ntfy import NtfyEnvironmentNotifier, TrustedDashboardLink


def resolve_notification_topic(
    settings: AppSettings | None,
    environ: Mapping[str, str],
) -> str:
    topic = environ.get("NTFY_TOPIC", "").strip()
    if not topic and settings is not None:
        topic = settings.notifications.ntfy_topic.strip()
    if not topic or topic == "replace-with-private-topic":
        raise ValueError("a private ntfy topic must be configured")
    return topic


def build_environment_notifier(
    settings: AppSettings | None,
    environ: Mapping[str, str],
) -> NtfyEnvironmentNotifier | None:
    dashboard_url = environ.get("BABY_MONITOR_DASHBOARD_URL", "").strip()
    if not dashboard_url:
        return None
    topic = resolve_notification_topic(settings, environ)
    token_name = (
        settings.notifications.ntfy_token_env if settings is not None else "NTFY_TOKEN"
    )
    return NtfyEnvironmentNotifier(
        ntfy_base_url=environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
        topic=topic,
        token=environ.get(token_name) or None,
        dashboard_link=TrustedDashboardLink(url=dashboard_url),
    )
