from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Train pinned YOLOX-Tiny on Intel CPU")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--dataset", type=Path, required=True)
    command.add_argument("--checkpoint", type=Path, required=True)
    command.add_argument("--epochs", type=int, default=80)
    command.add_argument("--batch-size", type=int, default=4)
    return command


def main() -> int:
    arguments = parser().parse_args()
    if not 1 <= arguments.epochs <= 300 or not 1 <= arguments.batch_size <= 16:
        return 2
    sys.path.insert(0, str(arguments.source))
    try:
        import cv2
        import numpy as np
        import torch
        from yolox.exp import get_exp

        torch.manual_seed(20210816)
        np.random.seed(20210816)
        random.seed(20210816)
        torch.set_num_threads(max(1, min(8, (os_cpu_count() or 1))))
        exp = get_exp(str(arguments.source / "exps/default/yolox_tiny.py"), None)
        exp.num_classes = 1
        exp.input_size = (640, 640)
        exp.test_size = (640, 640)
        model = exp.get_model().cpu()
        optimizer = exp.get_optimizer(arguments.batch_size)
        samples = _load_samples(arguments.dataset)
        best_loss = float("inf")
        best_state = None
        for epoch in range(arguments.epochs):
            order = list(range(len(samples)))
            random.Random(20210816 + epoch).shuffle(order)
            total_loss = 0.0
            batches = 0
            model.train()
            for start in range(0, len(order), arguments.batch_size):
                selected = [samples[index] for index in order[start : start + arguments.batch_size]]
                images, targets = _batch(selected, cv2=cv2, np=np, torch=torch)
                outputs = model(images, targets)
                loss = outputs["total_loss"]
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                total_loss += float(loss.detach())
                batches += 1
            epoch_loss = total_loss / max(1, batches)
            if epoch_loss < best_loss:
                best_loss = epoch_loss
                best_state = {key: value.detach().cpu() for key, value in model.state_dict().items()}
        if best_state is None:
            return 2
        arguments.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"model": best_state}, arguments.checkpoint)
        arguments.checkpoint.chmod(0o600)
        return 0
    except Exception:
        return 2


def os_cpu_count() -> int | None:
    import os

    return os.cpu_count()


def _load_samples(dataset: Path) -> list[dict[str, object]]:
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="ascii"))
    if manifest.get("input_size") != 640 or not isinstance(manifest.get("samples"), list):
        raise ValueError("ws2021_training_failed")
    samples = [sample for sample in manifest["samples"] if sample.get("split") == "train"]
    if not samples:
        raise ValueError("ws2021_training_failed")
    return [{**sample, "dataset": dataset} for sample in samples]


def _batch(samples: list[dict[str, object]], *, cv2: object, np: object, torch: object):
    images = []
    targets = []
    for sample in samples:
        dataset = sample["dataset"]
        image = cv2.imread(str(dataset / sample["image"]))
        if image is None or image.shape[:2] != (640, 640):
            raise ValueError("ws2021_training_failed")
        images.append(image.transpose(2, 0, 1).astype("float32"))
        target = np.zeros((1, 5), dtype=np.float32)
        label = (dataset / sample["label"]).read_text(encoding="ascii").split()
        if label:
            if len(label) != 5 or label[0] != "0":
                raise ValueError("ws2021_training_failed")
            target[0] = [0.0, *(float(value) * 640 for value in label[1:])]
        targets.append(target)
    return torch.from_numpy(np.stack(images)), torch.from_numpy(np.stack(targets))


if __name__ == "__main__":
    raise SystemExit(main())
