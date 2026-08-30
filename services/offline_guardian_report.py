from __future__ import annotations

import html
import os
import stat
from pathlib import Path

from packages.contracts.offline_guardian_scenario import (
    OfflineScenarioRunV1,
    canonical_offline_run_bytes,
)


MAX_REPORT_JSON_BYTES = 256 * 1024
MAX_REPORT_HTML_BYTES = 512 * 1024
JSON_NAME = "scenario-result.v1.json"
HTML_NAME = "scenario-report.html"


def publish_offline_scenario_report(
    run: OfflineScenarioRunV1,
    destination: Path,
) -> tuple[Path, Path]:
    root = Path(destination)
    if not _private_empty_directory(root):
        raise ValueError("offline_scenario_report_unsafe")

    json_bytes = canonical_offline_run_bytes(run)
    html_bytes = _render_html(run).encode("ascii")
    if len(json_bytes) > MAX_REPORT_JSON_BYTES or len(html_bytes) > MAX_REPORT_HTML_BYTES:
        raise ValueError("offline_scenario_report_too_large")

    json_path = root / JSON_NAME
    html_path = root / HTML_NAME
    json_temp = root / ".scenario-result.v1.json.tmp"
    html_temp = root / ".scenario-report.html.tmp"
    identities: dict[Path, tuple[int, int]] = {}
    published: list[Path] = []
    try:
        _write_private(json_temp, json_bytes)
        _write_private(html_temp, html_bytes)
        identities = {
            json_path: _file_identity(json_temp),
            html_path: _file_identity(html_temp),
        }
        _link_no_replace(json_temp, json_path)
        published.append(json_path)
        _link_no_replace(html_temp, html_path)
        published.append(html_path)
        _fsync_directory(root)
        json_temp.unlink()
        html_temp.unlink()
        _fsync_directory(root)
    except BaseException as exc:
        for final in reversed(published):
            _unlink_same_inode(final, identities.get(final))
        for temporary in (json_temp, html_temp):
            _unlink_private_temp(temporary)
        _fsync_directory_best_effort(root)
        if isinstance(exc, OSError):
            raise ValueError("offline_scenario_report_failed") from None
        raise
    return json_path, html_path


def _render_html(run: OfflineScenarioRunV1) -> str:
    rows: list[str] = []
    for result in run.results:
        for lane in result.lanes:
            counts = ", ".join(
                f"{html.escape(key)}={value}"
                for key, value in sorted(lane.counts.items())
            ) or "none"
            metrics = ", ".join(
                f"{html.escape(key)}={value:.3f}ms"
                for key, value in sorted(lane.metrics_ms.items())
            ) or "none"
            rows.append(
                "<tr>"
                f"<td>{html.escape(result.scenario_id)}</td>"
                f"<td>{html.escape(lane.lane)}</td>"
                f"<td>{html.escape(lane.status)}</td>"
                f"<td>{html.escape(lane.reason)}</td>"
                f"<td>{html.escape(result.visual_oracle_relationship or 'none')}</td>"
                f"<td>{counts}</td>"
                f"<td>{metrics}</td>"
                "</tr>"
            )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Offline Guardian Scenario Report</title>"
        "<style>body{font-family:sans-serif;margin:2rem}table{border-collapse:collapse}"
        "th,td{border:1px solid #999;padding:.4rem;text-align:left}</style></head>"
        "<body><h1>Offline Guardian Scenario Report</h1>"
        f"<p>suite={html.escape(run.suite_id)} status={html.escape(run.status)} "
        f"reason={html.escape(run.reason)}</p>"
        "<p>This offline regression does not prove model accuracy, household-scene "
        "accuracy, camera compatibility, notification delivery or unattended-care "
        "safety. Guardian counts are synthetic-oracle results; PASS means they matched "
        "the tracked expectations.</p>"
        "<table><thead><tr><th>scenario</th><th>lane</th><th>status</th>"
        "<th>reason</th><th>visual/oracle relationship</th><th>counts</th>"
        "<th>metrics</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def _private_empty_directory(root: Path) -> bool:
    try:
        metadata = root.lstat()
        entries = tuple(root.iterdir())
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not _path_has_symlink(root)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
        and not entries
    )


def _write_private(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _link_no_replace(source: Path, target: Path) -> None:
    os.link(source, target, follow_symlinks=False)


def _file_identity(path: Path) -> tuple[int, int]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError
    return metadata.st_dev, metadata.st_ino


def _unlink_same_inode(path: Path, identity: tuple[int, int] | None) -> None:
    try:
        path_info = path.lstat()
        if (
            identity is not None
            and stat.S_ISREG(path_info.st_mode)
            and (path_info.st_dev, path_info.st_ino) == identity
        ):
            path.unlink()
    except OSError:
        return


def _unlink_private_temp(path: Path) -> None:
    try:
        metadata = path.lstat()
        if (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == os.getuid()
            and stat.S_IMODE(metadata.st_mode) == 0o600
        ):
            path.unlink()
    except OSError:
        return


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory_best_effort(path: Path) -> None:
    try:
        _fsync_directory(path)
    except OSError:
        return


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


__all__ = ["publish_offline_scenario_report"]
