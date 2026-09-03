from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from packages.contracts.offline_application_rehearsal import OfflineApplicationRunV1
from tests.contracts.test_offline_application_rehearsal import run_payload


def run() -> OfflineApplicationRunV1:
    return OfflineApplicationRunV1.model_validate(run_payload())


def private_root(path: Path) -> Path:
    path.mkdir(mode=0o700)
    path.chmod(0o700)
    return path


def test_report_is_private_canonical_bounded_and_contains_closed_sections(tmp_path: Path) -> None:
    from services.offline_application_report import publish_offline_application_report

    root = private_root(tmp_path / "report")
    json_path, html_path = publish_offline_application_report(run(), root)
    assert json_path.name == "application-result.v1.json"
    assert html_path.name == "application-report.html"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(json_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(html_path.stat().st_mode) == 0o600
    assert len(json_path.read_bytes()) <= 512 * 1024
    assert len(html_path.read_bytes()) <= 1024 * 1024
    html = html_path.read_text("ascii")
    for value in ("HISTORICAL", "SOFTWARE_REHEARSAL", "PANORAMIC_DEVICE", "not executed"):
        assert value in html
    assert "control-flow evidence only" in html


def test_report_rejects_nonempty_and_symlink_roots(tmp_path: Path) -> None:
    from services.offline_application_report import publish_offline_application_report

    nonempty = private_root(tmp_path / "nonempty")
    (nonempty / "existing").write_text("x")
    target = private_root(tmp_path / "target")
    link = tmp_path / "link"
    link.symlink_to(target)
    for candidate in (nonempty, link):
        with pytest.raises(ValueError, match="offline_application_report_unsafe"):
            publish_offline_application_report(run(), candidate)


def test_partial_publication_failure_leaves_no_final_or_temp(tmp_path: Path, monkeypatch) -> None:
    import services.offline_application_report as module

    root = private_root(tmp_path / "report")
    actual = module._link_no_replace
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private failure")
        actual(source, target)

    monkeypatch.setattr(module, "_link_no_replace", fail_second)
    with pytest.raises(ValueError, match="offline_application_report_failed"):
        module.publish_offline_application_report(run(), root)
    assert tuple(root.iterdir()) == ()


def test_outputs_exclude_private_and_media_fields(tmp_path: Path) -> None:
    from services.offline_application_report import publish_offline_application_report

    root = private_root(tmp_path / "report")
    paths = publish_offline_application_report(run(), root)
    payload = b"\n".join(path.read_bytes() for path in paths).lower()
    for forbidden in (b"transcript", b"exception", b"source_url", b"hostname", b"token", b"audio_bytes", b"media_path", b"/users/"):
        assert forbidden not in payload
