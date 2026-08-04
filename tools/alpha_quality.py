#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    inspect_quality,
    rollback_latest,
)


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

    return parser


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
        return 0

    if args.command == "rollback":
        restored = rollback_latest(args.config, args.backups)
        print(f"restored={restored}")
        return 0

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
