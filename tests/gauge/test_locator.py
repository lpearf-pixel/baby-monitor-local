from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import json
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from services.stream.frame_source import CapturedFrame


def frame(width: int = 2560, height: int = 1440) -> CapturedFrame:
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="JPEG")
    return CapturedFrame(
        jpeg=output.getvalue(),
        captured_at=datetime(2026, 8, 16, tzinfo=UTC),
        width=width,
        height=height,
    )


class Backend:
    model_version = "ws2021-test-v1"

    def __init__(self, rows: list[list[float]]) -> None:
        self.rows = np.asarray([rows], dtype=np.float32)
        self.input_shape: tuple[int, ...] | None = None

    def infer(self, tensor: np.ndarray) -> np.ndarray:
        self.input_shape = tensor.shape
        return self.rows


def test_locator_decodes_one_upright_candidate_to_source_coordinates() -> None:
    from services.gauge.locator import GaugeLocator

    backend = Backend([[320, 320, 128, 142, 0.95, 0.95]])
    location = GaugeLocator(backend=backend).locate(frame())

    assert backend.input_shape == (1, 3, 640, 640)
    assert location.model_version == "ws2021-test-v1"
    assert location.confidence == pytest.approx(0.9025)
    assert location.box.x == pytest.approx(0.4)
    assert location.box.width == pytest.approx(0.2)
    assert location.box.y == pytest.approx(0.3, abs=0.003)
    assert location.box.height == pytest.approx(0.39444, abs=0.0001)


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], "gauge_not_found"),
        (
            [
                [200, 320, 96, 112, 0.95, 0.95],
                [440, 320, 96, 112, 0.94, 0.95],
            ],
            "gauge_ambiguous",
        ),
        ([[20, 320, 128, 142, 0.95, 0.95]], "gauge_box_invalid"),
        ([[320, 320, 40, 45, 0.95, 0.95]], "gauge_box_invalid"),
        ([[320, 320, 180, 80, 0.95, 0.95]], "gauge_pose_invalid"),
    ],
)
def test_locator_fails_closed_for_invalid_candidates(
    rows: list[list[float]],
    code: str,
) -> None:
    from services.gauge.locator import GaugeLocalizationError, GaugeLocator

    with pytest.raises(GaugeLocalizationError) as caught:
        GaugeLocator(backend=Backend(rows)).locate(frame())

    assert caught.value.code.value == code
    assert str(caught.value) == code


@pytest.mark.parametrize(
    "rows",
    [
        [[320, 320, 128, 142, 0.95]],
        [[320, 320, -128, 142, 0.95, 0.95]],
        [[320, 320, 128, 142, 1.01, 0.95]],
    ],
)
def test_locator_rejects_malformed_backend_output(
    rows: list[list[float]],
) -> None:
    from services.gauge.locator import GaugeLocalizationError, GaugeLocator

    backend = Backend(rows)
    with pytest.raises(GaugeLocalizationError) as caught:
        GaugeLocator(backend=backend).locate(frame())
    assert caught.value.code.value == "gauge_model_invalid"


def test_openvino_backend_verifies_private_artifacts_and_fixed_shapes(
    tmp_path: Path,
) -> None:
    from services.gauge.locator import OpenVinoGaugeBackend

    model = tmp_path / "ws2021.xml"
    weights = tmp_path / "ws2021.bin"
    model.write_bytes(b"synthetic-xml")
    weights.write_bytes(b"synthetic-bin")
    metadata = {
        "architecture": "YOLOX-Tiny",
        "input_size": 640,
        "model_version": "ws2021-test-v1",
        "openvino_precision": "FP16",
        "sha256": {
            "ws2021.onnx": "0" * 64,
            "ws2021.xml": sha256(model.read_bytes()).hexdigest(),
            "ws2021.bin": sha256(weights.read_bytes()).hexdigest(),
        },
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="ascii")

    class Port:
        def __init__(self, shape: tuple[int, ...]) -> None:
            self.shape = shape

    class Compiled:
        def input(self, index: int) -> Port:
            return Port((1, 3, 640, 640))

        def output(self, index: int) -> Port:
            return Port((1, 8400, 6))

        def __call__(self, inputs: list[np.ndarray]) -> dict[int, np.ndarray]:
            assert inputs[0].shape == (1, 3, 640, 640)
            return {0: np.zeros((1, 8400, 6), dtype=np.float32)}

    class Core:
        def read_model(self, path: Path) -> object:
            assert path == model
            return object()

        def compile_model(self, loaded: object, device: str) -> Compiled:
            assert device == "CPU"
            return Compiled()

    backend = OpenVinoGaugeBackend(
        model_path=model,
        metadata_path=metadata_path,
        core=Core(),
    )

    assert backend.model_version == "ws2021-test-v1"
    assert backend.infer(np.zeros((1, 3, 640, 640), dtype=np.float32)).shape == (
        1,
        8400,
        6,
    )

    model.write_bytes(b"tampered")
    with pytest.raises(Exception) as caught:
        OpenVinoGaugeBackend(
            model_path=model,
            metadata_path=metadata_path,
            core=Core(),
        )
    assert getattr(caught.value, "code").value == "gauge_model_invalid"
