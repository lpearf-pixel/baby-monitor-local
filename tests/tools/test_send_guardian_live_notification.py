from __future__ import annotations

from pathlib import Path

import apps.api.runtime as runtime_module
import tools.send_guardian_live_notification as live_notification


class RecordingGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def send_test_notification(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


class AcceptedResponse:
    status = 202

    def __enter__(self) -> "AcceptedResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_send_live_notification_calls_gateway_once() -> None:
    gateway = RecordingGateway()

    assert live_notification.send_live_notification(lambda: gateway) is True
    assert gateway.calls == 1


def test_send_live_notification_redacts_gateway_factory_failure(capsys) -> None:
    def broken_gateway() -> object:
        raise RuntimeError("secret topic at private path")

    assert live_notification.send_live_notification(broken_gateway) is False
    assert capsys.readouterr() == ("", "")


def test_send_live_notification_redacts_gateway_failure(capsys) -> None:
    gateway = RecordingGateway(RuntimeError("credential and private address"))

    assert live_notification.send_live_notification(lambda: gateway) is False
    assert gateway.calls == 1
    assert capsys.readouterr() == ("", "")


def test_main_returns_stable_exit_status_without_output(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(live_notification, "send_live_notification", lambda: True)
    assert live_notification.main() == 0
    assert capsys.readouterr() == ("", "")

    monkeypatch.setattr(live_notification, "send_live_notification", lambda: False)
    assert live_notification.main() == 1
    assert capsys.readouterr() == ("", "")


def test_live_notification_does_not_initialize_dashboard_database(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        f"""
app:
  data_dir: {tmp_path.as_posix()}
camera:
  identifier: synthetic-camera
  model: MJSXJ17CM
  account_secret_env: MI_ACCOUNT_SECRET_REF
notifications:
  ntfy_topic: private-topic
  ntfy_token_env: NTFY_TOKEN_SECRET_REF
  enable_wecom: false
security:
  session_secret_env: SESSION_SECRET_REF
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("BABY_MONITOR_USERNAME", "parent")
    monkeypatch.setenv("BABY_MONITOR_PASSWORD", "dedicated-secret")
    monkeypatch.setenv("BABY_MONITOR_SETTINGS_PATH", str(settings))
    monkeypatch.setenv("NTFY_BASE_URL", "https://ntfy.example.test")
    monkeypatch.setenv("NTFY_TOPIC", "private-topic")
    monkeypatch.setattr(
        runtime_module,
        "urlopen",
        lambda _request, timeout: AcceptedResponse(),
    )

    assert live_notification.send_live_notification() is True
    assert not (tmp_path / "environment.sqlite3").exists()
