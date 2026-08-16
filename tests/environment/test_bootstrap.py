from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.events import EnvironmentSourceKind
from packages.contracts.settings import (
    AppSettings,
    CameraSettings,
    EnvironmentSettings,
    NotificationSettings,
    SecuritySettings,
)
from services.environment.notification_config import resolve_notification_topic


def settings(*, source_kind: EnvironmentSourceKind = EnvironmentSourceKind.WS2021_GAUGE) -> AppSettings:
    return AppSettings(
        camera=CameraSettings(
            identifier="nursery-main",
            model="MJSXJ17CM",
            account_secret_env="MI_ACCOUNT_SECRET_REF",
        ),
        environment=EnvironmentSettings(source_kind=source_kind),
        notifications=NotificationSettings(
            ntfy_topic="replace-with-private-topic",
            ntfy_token_env="NTFY_TOKEN",
            enable_wecom=False,
        ),
        security=SecuritySettings(session_secret_env="SESSION_SECRET_REF"),
    )


def test_runtime_ntfy_topic_overrides_public_example_placeholder() -> None:
    assert resolve_notification_topic(
        settings(), {"NTFY_TOPIC": "baby-monitor-random-private-topic"}
    ) == "baby-monitor-random-private-topic"


def test_placeholder_topic_without_runtime_override_fails_closed() -> None:
    with pytest.raises(ValueError, match="private ntfy topic"):
        resolve_notification_topic(settings(), {})


def test_unimplemented_source_kind_is_rejected_before_worker_composition(
    tmp_path: Path,
) -> None:
    from services.environment.bootstrap import build_gauge_worker

    with pytest.raises(ValueError, match="source_kind is not implemented"):
        build_gauge_worker(
            settings(source_kind=EnvironmentSourceKind.MQTT),
            tmp_path,
            {},
        )


def test_auto_localization_composes_fixed_openvino_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.environment import bootstrap

    observed: dict[str, Path] = {}

    class Backend:
        model_version = "test-v1"

        def __init__(self, *, model_path: Path, metadata_path: Path) -> None:
            observed["model"] = model_path
            observed["metadata"] = metadata_path

        def infer(self, tensor: object) -> object:
            raise AssertionError("inference is not part of composition")

    monkeypatch.setattr(bootstrap, "OpenVinoGaugeBackend", Backend)
    configured = settings().model_copy(
        update={
            "environment": EnvironmentSettings(auto_localization=True),
        }
    )

    worker = bootstrap.build_gauge_worker(configured, tmp_path, {})

    assert worker._source._locator is not None
    assert observed == {
        "model": tmp_path / "runtime/training/ws2021/model/ws2021.xml",
        "metadata": tmp_path / "runtime/training/ws2021/model/metadata.json",
    }
