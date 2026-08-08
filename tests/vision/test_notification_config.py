from __future__ import annotations

import pytest

from packages.contracts.settings import (
    AppSettings,
    CameraSettings,
    NotificationSettings,
    SecuritySettings,
)
from services.notifications.visual_ntfy import NtfyVisualHealthNotifier
from services.vision.notification_config import build_visual_health_notifier


def settings() -> AppSettings:
    return AppSettings(
        camera=CameraSettings(
            identifier="nursery-main",
            model="MJSXJ17CM",
            account_secret_env="MI_ACCOUNT_SECRET_REF",
        ),
        notifications=NotificationSettings(
            ntfy_topic="replace-with-private-topic",
            ntfy_token_env="VISUAL_NTFY_TOKEN",
            enable_wecom=False,
        ),
        security=SecuritySettings(session_secret_env="SESSION_SECRET_REF"),
    )


def test_builder_uses_runtime_topic_and_referenced_token_without_dashboard_url() -> None:
    built = build_visual_health_notifier(
        settings(),
        {
            "NTFY_TOPIC": "baby-monitor-random-private-topic",
            "VISUAL_NTFY_TOKEN": "runtime-secret",
        },
    )

    assert isinstance(built, NtfyVisualHealthNotifier)
    assert built._topic == "baby-monitor-random-private-topic"
    assert built._token == "runtime-secret"


def test_builder_fails_closed_for_public_example_topic() -> None:
    with pytest.raises(ValueError, match="private ntfy topic"):
        build_visual_health_notifier(settings(), {})

