from __future__ import annotations

import html
from pathlib import Path

from packages.contracts.offline_application_rehearsal import (
    OfflineApplicationRunV1,
    canonical_application_run_bytes,
)
from services.offline_guardian_report import (
    _file_identity,
    _fsync_directory,
    _fsync_directory_best_effort,
    _link_no_replace,
    _private_empty_directory,
    _unlink_private_temp,
    _unlink_same_inode,
    _write_private,
)


MAX_REPORT_JSON_BYTES = 512 * 1024
MAX_REPORT_HTML_BYTES = 1024 * 1024
JSON_NAME = "application-result.v1.json"
HTML_NAME = "application-report.html"


def publish_offline_application_report(
    run: OfflineApplicationRunV1,
    destination: Path,
) -> tuple[Path, Path]:
    root = Path(destination)
    if not _private_empty_directory(root):
        raise ValueError("offline_application_report_unsafe")
    json_bytes = canonical_application_run_bytes(run)
    html_bytes = _render_html(run).encode("ascii")
    if len(json_bytes) > MAX_REPORT_JSON_BYTES or len(html_bytes) > MAX_REPORT_HTML_BYTES:
        raise ValueError("offline_application_report_too_large")
    json_path = root / JSON_NAME
    html_path = root / HTML_NAME
    json_temp = root / ".application-result.v1.json.tmp"
    html_temp = root / ".application-report.html.tmp"
    identities: dict[Path, tuple[int, int]] = {}
    published: list[Path] = []
    try:
        _write_private(json_temp, json_bytes)
        _write_private(html_temp, html_bytes)
        identities = {json_path: _file_identity(json_temp), html_path: _file_identity(html_temp)}
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
            raise ValueError("offline_application_report_failed") from None
        raise
    return json_path, html_path


def _render_html(run: OfflineApplicationRunV1) -> str:
    historical = "".join(
        "<li>" + html.escape(item.evidence_id) + "=" + html.escape(item.result) + "</li>"
        for item in run.historical
    )
    scenarios = "".join(
        "<tr><td>" + html.escape(item.scenario_id) + "</td><td>"
        + html.escape(item.lane) + "</td><td>" + html.escape(item.status)
        + "</td><td>" + html.escape(item.reason) + "</td></tr>"
        for item in run.results
    )
    faults = "".join(
        "<li>" + html.escape(item.fault_id) + "=" + html.escape(item.outcome)
        + "/" + html.escape(item.reason) + "</li>"
        for item in run.faults
    )
    required_zero_keys = (
        "no_baby_face_watch", "no_baby_face_alert", "no_baby_face_event",
        "no_baby_face_notification", "residual_reply_sessions",
    )
    zero_values = tuple(run.side_effects.model_dump().items()) + tuple(
        (key, run.counts[key]) for key in required_zero_keys
    )
    zeroes = "".join(
        "<li>" + html.escape(key) + "=" + str(int(value)) + "</li>"
        for key, value in zero_values
    )
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Offline Application Rehearsal</title></head><body>"
        "<h1>Offline Application Rehearsal</h1>"
        f"<p>SOFTWARE_REHEARSAL={html.escape(run.status)}</p>"
        "<p>Software PASS is control-flow evidence only and does not publish live Voice, "
        "visual accuracy or Camera Reply PASS.</p>"
        "<h2>HISTORICAL</h2><ul>" + historical + "</ul>"
        "<h2>SOFTWARE_REHEARSAL</h2><table><tbody>" + scenarios + "</tbody></table>"
        "<h2>Faults</h2><ul>" + faults + "</ul>"
        "<h2>Closed side effects</h2><ul>" + zeroes + "</ul>"
        f"<p>iterations={len(run.repetition.iterations)} "
        f"cross_risk={run.repetition.cross_risk_pass}/{run.repetition.cross_risk_instances}</p>"
        "<h2>PANORAMIC_DEVICE</h2><p>not executed</p>"
        "</body></html>"
    )


__all__ = ["publish_offline_application_report"]
