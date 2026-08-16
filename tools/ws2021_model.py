from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path


YOLOX_URL = "https://github.com/Megvii-BaseDetection/YOLOX.git"
YOLOX_COMMIT = "419778480ab6ec0590e5d3831b3afb3b46ab2aa3"
TRAIN_PACKAGES = (
    "numpy==1.26.4",
    "torch==2.2.2",
    "torchvision==0.17.2",
    "opencv-python-headless==4.10.0.84",
    "loguru==0.7.3",
    "tabulate==0.9.0",
    "thop==0.1.1.post2209072238",
    "onnx==1.16.2",
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Manage the private WS2021 model")
    command.add_argument("action", choices=("bootstrap", "prepare", "train", "export", "check"))
    command.add_argument("--root", type=Path, default=Path("runtime/training/ws2021"))
    return command


def main() -> int:
    arguments = parser().parse_args()
    try:
        _run_action(arguments.action, arguments.root)
    except Exception:
        print(f"ws2021_model={arguments.action}_failed")
        return 2
    print(f"ws2021_model={arguments.action}_ok")
    return 0


def _run_action(action: str, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    source = root / "YOLOX"
    venv = root / "venv"
    dataset = root / "dataset"
    artifacts = root / "model"
    if action == "bootstrap":
        _run((sys.executable, "-m", "venv", str(venv)))
        _run((str(venv / "bin/pip"), "install", "--disable-pip-version-check", *TRAIN_PACKAGES))
    elif action == "prepare":
        if not source.exists():
            _run(("git", "clone", "--no-checkout", YOLOX_URL, str(source)))
        _run(("git", "-C", str(source), "checkout", "--detach", YOLOX_COMMIT))
        _verify_source(source)
    elif action == "train":
        _verify_source(source)
        _require_dataset(dataset)
        _run(
            (
                str(venv / "bin/python"),
                str(Path(__file__).with_name("ws2021_cpu_train.py")),
                "--source", str(source),
                "--dataset", str(dataset),
                "--checkpoint", str(artifacts / "best_ckpt.pth"),
            ),
            offline=True,
        )
    elif action == "export":
        _verify_source(source)
        checkpoint = artifacts / "best_ckpt.pth"
        if not checkpoint.is_file():
            raise ValueError("ws2021_model_invalid")
        artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
        experiment = artifacts / "ws2021_exp.py"
        _write_private(experiment, _experiment_source().encode("ascii"))
        onnx_path = artifacts / "ws2021.onnx"
        _run(
            (
                str(venv / "bin/python"),
                str(source / "tools/export_onnx.py"),
                "--output-name", str(onnx_path),
                "--no-onnxsim",
                "--decode_in_inference",
                "-f", str(experiment),
                "-c", str(checkpoint),
            ),
            offline=True,
        )
        _convert_openvino(onnx_path, artifacts / "ws2021.xml")
        _write_metadata(artifacts)
    elif action == "check":
        _verify_source(source)
        _verify_artifacts(artifacts)
    else:
        raise ValueError("ws2021_model_invalid")


def _run(command: tuple[str, ...], *, offline: bool = False) -> None:
    environment = os.environ.copy()
    environment.update({"WANDB_MODE": "disabled", "YOLOX_NO_NETWORK": "1"})
    if offline:
        environment.update({"PIP_NO_INDEX": "1", "HF_HUB_OFFLINE": "1"})
    subprocess.run(
        command,
        check=True,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=None,
    )


def _verify_source(source: Path) -> None:
    completed = subprocess.run(
        ("git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip() != YOLOX_COMMIT:
        raise ValueError("ws2021_model_invalid")
    license_text = (source / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("ws2021_model_invalid")


def _require_dataset(dataset: Path) -> None:
    payload = json.loads((dataset / "manifest.json").read_text(encoding="ascii"))
    if payload.get("input_size") != 640 or not payload.get("samples"):
        raise ValueError("ws2021_model_invalid")


def _experiment_source() -> str:
    return """from yolox.exp import Exp as BaseExp

class Exp(BaseExp):
    def __init__(self):
        super().__init__()
        self.num_classes = 1
        self.depth = 0.33
        self.width = 0.375
        self.input_size = (640, 640)
        self.test_size = (640, 640)
        self.exp_name = "ws2021_yolox_tiny"
"""


def _convert_openvino(onnx_path: Path, xml_path: Path) -> None:
    import openvino as ov

    model = ov.convert_model(onnx_path, input=[1, 3, 640, 640])
    ov.save_model(model, xml_path, compress_to_fp16=True)
    os.chmod(xml_path, 0o600)
    os.chmod(xml_path.with_suffix(".bin"), 0o600)


def _write_metadata(artifacts: Path) -> None:
    files = ("ws2021.onnx", "ws2021.xml", "ws2021.bin")
    metadata = {
        "architecture": "YOLOX-Tiny",
        "input_size": 640,
        "model_version": f"ws2021-{YOLOX_COMMIT[:12]}",
        "openvino_precision": "FP16",
        "sha256": {name: _digest(artifacts / name) for name in files},
        "yolox_commit": YOLOX_COMMIT,
    }
    _write_private(
        artifacts / "metadata.json",
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )


def _verify_artifacts(artifacts: Path) -> None:
    metadata = json.loads((artifacts / "metadata.json").read_text(encoding="ascii"))
    digests = metadata.get("sha256")
    if (
        metadata.get("yolox_commit") != YOLOX_COMMIT
        or metadata.get("input_size") != 640
        or not isinstance(digests, dict)
        or set(digests) != {"ws2021.onnx", "ws2021.xml", "ws2021.bin"}
    ):
        raise ValueError("ws2021_model_invalid")
    for name, expected in digests.items():
        if name not in {"ws2021.onnx", "ws2021.xml", "ws2021.bin"} or _digest(artifacts / name) != expected:
            raise ValueError("ws2021_model_invalid")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
