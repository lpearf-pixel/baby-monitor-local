from __future__ import annotations

import argparse
from pathlib import Path

from packages.monitoring.realtime_models import (
    ModelAssetCode,
    install_realtime_model_assets,
    verify_realtime_model_assets,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Manage pinned realtime visual models")
    command.add_argument("action", choices=("check", "install"))
    command.add_argument(
        "--root",
        type=Path,
        default=Path("runtime/models/openvino-2025.4.1"),
    )
    return command


def main() -> int:
    arguments = parser().parse_args()
    status = (
        install_realtime_model_assets(arguments.root)
        if arguments.action == "install"
        else verify_realtime_model_assets(arguments.root)
    )
    print(f"realtime_models={status.code.value}")
    print(f"checked_count={status.checked_count}")
    return 0 if status.code is ModelAssetCode.OK else 2


if __name__ == "__main__":
    raise SystemExit(main())
