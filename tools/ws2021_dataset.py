from __future__ import annotations

import argparse
import json
from pathlib import Path

from packages.monitoring.ws2021_dataset import NegativeSample, build_training_dataset


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Build private WS2021 training data")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--negative-manifest", type=Path)
    command.add_argument("--augmentations", type=int, default=1)
    return command


def main() -> int:
    arguments = parser().parse_args()
    try:
        negatives = _load_negatives(arguments.negative_manifest)
        counts = build_training_dataset(
            arguments.source,
            arguments.output,
            negatives=negatives,
            augmentation_count=arguments.augmentations,
            synthetic_negative_count=64,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        print("ws2021_dataset=failed")
        return 2
    print("ws2021_dataset=ok")
    print(f"train_count={counts.train}")
    print(f"val_count={counts.val}")
    print(f"negative_count={counts.negative}")
    return 0


def _load_negatives(path: Path | None) -> tuple[NegativeSample, ...]:
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("ws2021_dataset_invalid")
    negatives: list[NegativeSample] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "license_id",
            "source_url",
        }:
            raise ValueError("ws2021_dataset_invalid")
        negatives.append(
            NegativeSample(
                path=Path(item["path"]),
                license_id=item["license_id"],
                source_url=item["source_url"],
            )
        )
    return tuple(negatives)


if __name__ == "__main__":
    raise SystemExit(main())
