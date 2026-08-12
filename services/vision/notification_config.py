from __future__ import annotations

from collections.abc import Mapping

from packages.contracts.settings import AppSettings
from services.environment.notification_config import resolve_notification_topic
from services.notifications.visual_ntfy import NtfyVisualHealthNotifier


def build_visual_health_notifier(
    settings: AppSettings,
    environ: Mapping[str, str],
) -> NtfyVisualHealthNotifier:
    topic = resolve_notification_topic(settings, environ)
    token_name = settings.notifications.ntfy_token_env
    return NtfyVisualHealthNotifier(
        ntfy_base_url=environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
        topic=topic,
        token=environ.get(token_name) or None,
    )
