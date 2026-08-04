#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.monitoring.alpha_quality import (  # noqa: E402
    QualityConfigError,
    apply_hd,
    check_hd_health,
    check_source_health,
    inspect_quality,
    rollback_latest,
)
from packages.monitoring.subtype_probe import apply_subtype, probe_subtypes  # noqa: E402


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _load_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the Baby Monitor Local Alpha preview quality safely."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    apply_parser = subparsers.add_parser(
        "apply-hd", help="Back up the runtime config and apply the HD profile."
    )
    apply_parser.add_argument("--config", required=True, type=_path)
    apply_parser.add_argument("--backups", required=True, type=_path)

    info_parser = subparsers.add_parser(
        "info", help="Print non-sensitive derived quality settings."
    )
    info_parser.add_argument("--config", required=True, type=_path)

    rollback_parser = subparsers.add_parser(
        "rollback", help="Restore the newest HD quality backup."
    )
    rollback_parser.add_argument("--config", required=True, type=_path)
    rollback_parser.add_argument("--backups", required=True, type=_path)

    check_parser = subparsers.add_parser(
        "check", help="Verify source media, HD frames, MJPEG, and dashboard health."
    )
    check_parser.add_argument("--base-url", required=True)
    check_parser.add_argument("--dashboard-url", required=True)

    probe_parser = subparsers.add_parser(
        "probe-subtypes",
        help="Safely measure Xiaomi source subtype candidates, then restore config.",
    )
    probe_parser.add_argument("--config", required=True, type=_path)
    probe_parser.add_argument("--backups", required=True, type=_path)
    probe_parser.add_argument("--base-url", required=True)
    probe_parser.add_argument("--candidates", required=True, nargs="+", type=int)
    probe_parser.add_argument("--restart-command", required=True)

    subtype_apply_parser = subparsers.add_parser(
        "apply-subtype",
        help="Apply a verified Xiaomi subtype transactionally with health rollback.",
    )
    subtype_apply_parser.add_argument("--config", required=True, type=_path)
    subtype_apply_parser.add_argument("--backups", required=True, type=_path)
    subtype_apply_parser.add_argument("--base-url", required=True)
    subtype_apply_parser.add_argument("--dashboard-url", required=True)
    subtype_apply_parser.add_argument("--subtype", required=True, type=int)
    subtype_apply_parser.add_argument("--minimum-width", required=True, type=int)
    subtype_apply_parser.add_argument("--minimum-height", required=True, type=int)
    subtype_apply_parser.add_argument("--restart-command", required=True)

    return parser


def _dimensions(value: tuple[int, int] | None) -> str:
    return "unavailable" if value is None else f"{value[0]}x{value[1]}"


def _restart_alpha(command: str) -> None:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise QualityConfigError("ALPHA_RESTART_FAILED") from exc
    if not argv:
        raise QualityConfigError("ALPHA_RESTART_FAILED")

    completed = subprocess.run(
        argv,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise QualityConfigError("ALPHA_RESTART_FAILED")


def _run(args: argparse.Namespace) -> int:
    if args.command == "apply-hd":
        backup = apply_hd(
            args.config,
            args.backups,
            datetime.now(timezone.utc),
        )
        print(f"backup={backup}")
        return 0

    if args.command == "info":
        info = inspect_quality(_load_config(args.config))
        print(f"source_quality={info.source_quality}")
        print(f"transport={info.transport}")
        print(f"live_width={info.live_width}")
        print(f"live_height={info.live_height}")
        print(f"live_fps={info.live_fps}")
        print(f"compat_profile={info.compat_profile}")
        return 0

    if args.command == "rollback":
        restored = rollback_latest(args.config, args.backups)
        print(f"restored={restored}")
        return 0

    if args.command == "check":
        result = check_hd_health(args.base_url, args.dashboard_url)
        print(f"result={result.code}")
        print(f"protocol={result.protocol or 'unavailable'}")
        print(f"source_codec={result.source_codec or 'unavailable'}")
        print(f"bytes_received={result.bytes_received}")
        print(f"source_dimensions={_dimensions(result.source_dimensions)}")
        print(f"live_dimensions={_dimensions(result.live_dimensions)}")
        return 0 if result.code == "PASS" else 2

    if args.command == "probe-subtypes":
        summary = probe_subtypes(
            args.config,
            args.backups,
            tuple(args.candidates),
            lambda: _restart_alpha(args.restart_command),
            lambda: check_source_health(args.base_url),
            datetime.now(timezone.utc),
        )
        for attempt in summary.attempts:
            print(
                f"subtype={attempt.subtype} result={attempt.code} "
                f"protocol={attempt.protocol or 'unavailable'} "
                f"bytes_received={attempt.bytes_received} "
                f"source_dimensions={_dimensions(attempt.source_dimensions)}"
            )
        recommended = (
            "unavailable"
            if summary.recommended_subtype is None
            else str(summary.recommended_subtype)
        )
        print(f"recommended_subtype={recommended}")
        print("original_config_restored=true")
        return 0 if summary.recommended_subtype is not None else 2

    if args.command == "apply-subtype":
        summary = apply_subtype(
            args.config,
            args.backups,
            args.subtype,
            (args.minimum_width, args.minimum_height),
            lambda: _restart_alpha(args.restart_command),
            lambda: check_hd_health(args.base_url, args.dashboard_url),
            datetime.now(timezone.utc),
        )
        health = summary.health
        print(f"result={health.code}")
        print(f"applied_subtype={summary.applied_subtype}")
        print(f"protocol={health.protocol or 'unavailable'}")
        print(f"bytes_received={health.bytes_received}")
        print(f"source_dimensions={_dimensions(health.source_dimensions)}")
        print(f"live_dimensions={_dimensions(health.live_dimensions)}")
        restored = "true" if summary.original_config_restored else "false"
        print(f"original_config_restored={restored}")
        return 0 if health.code == "PASS" else 2

    raise QualityConfigError("UNKNOWN_COMMAND")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        return _run(parser.parse_args(argv))
    except QualityConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
