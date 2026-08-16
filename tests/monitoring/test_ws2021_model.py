from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from tools import ws2021_model


def test_model_contract_pins_source_architecture_and_training_packages() -> None:
    assert ws2021_model.YOLOX_COMMIT == "419778480ab6ec0590e5d3831b3afb3b46ab2aa3"
    assert ws2021_model.YOLOX_URL == "https://github.com/Megvii-BaseDetection/YOLOX.git"
    assert "torch==2.2.2" in ws2021_model.TRAIN_PACKAGES
    assert "thop==0.1.1.post2209072238" in ws2021_model.TRAIN_PACKAGES
    experiment = ws2021_model._experiment_source()
    assert "self.num_classes = 1" in experiment
    assert "self.depth = 0.33" in experiment
    assert "self.width = 0.375" in experiment
    assert "self.input_size = (640, 640)" in experiment
    assert "wandb" not in experiment.lower()


def test_offline_runner_disables_network_loggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        observed.update(kwargs)

    monkeypatch.setattr(ws2021_model.subprocess, "run", fake_run)
    ws2021_model._run(("training-python", "trainer.py"), offline=True)
    environment = observed["env"]
    assert environment["WANDB_MODE"] == "disabled"  # type: ignore[index]
    assert environment["PIP_NO_INDEX"] == "1"  # type: ignore[index]
    assert observed["stdout"] is ws2021_model.subprocess.DEVNULL
    assert observed["stderr"] is ws2021_model.subprocess.DEVNULL


def test_artifact_check_requires_exact_files_and_digests(tmp_path: Path) -> None:
    artifacts = tmp_path / "model"
    artifacts.mkdir()
    digests: dict[str, str] = {}
    for name in ("ws2021.onnx", "ws2021.xml", "ws2021.bin"):
        payload = name.encode("ascii")
        (artifacts / name).write_bytes(payload)
        digests[name] = sha256(payload).hexdigest()
    (artifacts / "metadata.json").write_text(
        json.dumps(
            {
                "input_size": 640,
                "sha256": digests,
                "yolox_commit": ws2021_model.YOLOX_COMMIT,
            }
        ),
        encoding="ascii",
    )
    ws2021_model._verify_artifacts(artifacts)

    del digests["ws2021.bin"]
    (artifacts / "metadata.json").write_text(
        json.dumps(
            {
                "input_size": 640,
                "sha256": digests,
                "yolox_commit": ws2021_model.YOLOX_COMMIT,
            }
        ),
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="ws2021_model_invalid"):
        ws2021_model._verify_artifacts(artifacts)


def test_cli_failure_is_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["ws2021_model.py", "check", "--root", str(tmp_path)])
    assert ws2021_model.main() == 2
    output = capsys.readouterr().out
    assert output == "ws2021_model=check_failed\n"
    assert str(tmp_path) not in output
