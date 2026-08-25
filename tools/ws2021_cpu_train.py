from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
from hashlib import sha256
from pathlib import Path


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Train pinned YOLOX-Tiny on Intel CPU")
    command.add_argument("--source", type=Path)
    command.add_argument("--dataset", type=Path)
    command.add_argument("--checkpoint", type=Path, required=True)
    command.add_argument("--epochs", type=int, default=80)
    command.add_argument("--batch-size", type=int, default=4)
    command.add_argument("--read-checkpoint-provenance", action="store_true")
    return command


def main() -> int:
    arguments = parser().parse_args()
    if arguments.read_checkpoint_provenance:
        return _emit_checkpoint_training_provenance(arguments.checkpoint)
    if arguments.source is None or arguments.dataset is None:
        return 2
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
        optimizer = _cpu_optimizer(exp, batch_size=arguments.batch_size)
        samples = _load_samples(arguments.dataset)
        best_loss = float("inf")
        best_state = None
        best_epoch = None
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
                best_state = _snapshot_state(model.state_dict())
                best_epoch = epoch + 1
        if best_state is None or best_epoch is None:
            return 2
        arguments.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        provenance = _training_provenance(
            arguments.dataset,
            configured_epochs=arguments.epochs,
            best_epoch=best_epoch,
        )
        torch.save(
            {"model": best_state, "training_provenance": provenance},
            arguments.checkpoint,
        )
        arguments.checkpoint.chmod(0o600)
        _write_private_json(
            arguments.checkpoint.with_suffix(".provenance.json"),
            {
                **provenance,
                "checkpoint_sha256": _digest(arguments.checkpoint),
            },
        )
        return 0
    except Exception:
        return 2


def os_cpu_count() -> int | None:
    import os

    return os.cpu_count()


def _cpu_optimizer(exp: object, *, batch_size: int) -> object:
    exp.warmup_epochs = 0
    optimizer = exp.get_optimizer(batch_size)
    learning_rate = exp.basic_lr_per_img * batch_size
    if learning_rate <= 0:
        raise ValueError("ws2021_training_failed")
    for group in optimizer.param_groups:
        group["lr"] = learning_rate
    return optimizer


def _snapshot_state(state: dict[str, object]) -> dict[str, object]:
    return {
        key: value.detach().cpu().clone()
        for key, value in state.items()
    }


def _training_provenance(
    dataset: Path, *, configured_epochs: int, best_epoch: int
) -> dict[str, object]:
    if not 1 <= best_epoch <= configured_epochs <= 300:
        raise ValueError("ws2021_training_failed")
    return {
        "best_epoch": best_epoch,
        "configured_epochs": configured_epochs,
        "dataset_manifest_sha256": _digest(dataset / "manifest.json"),
    }


def _emit_checkpoint_training_provenance(checkpoint: Path) -> int:
    try:
        import torch

        payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
        if not isinstance(payload, dict):
            raise ValueError("ws2021_training_failed")
        provenance = _validate_training_provenance(payload.get("training_provenance"))
        print(json.dumps(provenance, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        return 2


def _validate_training_provenance(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "best_epoch",
        "configured_epochs",
        "dataset_manifest_sha256",
    }:
        raise ValueError("ws2021_training_failed")
    configured_epochs = value["configured_epochs"]
    best_epoch = value["best_epoch"]
    manifest_digest = value["dataset_manifest_sha256"]
    if (
        type(configured_epochs) is not int
        or type(best_epoch) is not int
        or not 1 <= best_epoch <= configured_epochs <= 300
        or not isinstance(manifest_digest, str)
        or len(manifest_digest) != 64
        or any(character not in "0123456789abcdef" for character in manifest_digest)
    ):
        raise ValueError("ws2021_training_failed")
    return {
        "best_epoch": best_epoch,
        "configured_epochs": configured_epochs,
        "dataset_manifest_sha256": manifest_digest,
    }


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o600)
        descriptor = -1
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            if descriptor >= 0:
                os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)


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
