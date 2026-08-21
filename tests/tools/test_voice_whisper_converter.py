from __future__ import annotations

import pytest
import numpy as np
from types import SimpleNamespace

from tools.voice_whisper_converter import (
    PINNED_PACKAGES,
    _install_numpy_loader_overrides,
    require_pinned_packages,
)


def test_converter_requires_the_exact_isolated_dependency_set() -> None:
    assert PINNED_PACKAGES == {
        "ctranslate2": "4.8.1",
        "numpy": "1.26.4",
        "pydantic": "2.13.4",
        "torch": "2.2.2",
        "transformers": "4.56.2",
    }
    require_pinned_packages(lambda package: PINNED_PACKAGES[package])


def test_converter_rejects_a_dependency_drift_without_exposing_details() -> None:
    def drifted(package: str) -> str:
        return "0.0.0" if package == "torch" else PINNED_PACKAGES[package]

    with pytest.raises(RuntimeError, match="^VOICE_CONVERTER_UNAVAILABLE$"):
        require_pinned_packages(drifted)


class _Tensor:
    def __init__(self, values: list[list[float]] | list[float]) -> None:
        self.values = np.array(values, dtype=np.float32)

    def detach(self) -> "_Tensor":
        return self

    def cpu(self) -> "_Tensor":
        return self

    def numpy(self) -> np.ndarray:
        return self.values

    def transpose(self, first: int, second: int) -> "_Tensor":
        assert (first, second) == (0, 1)
        return _Tensor(self.values.T.tolist())


class _Conv1D:
    pass


def test_numpy_overrides_cover_whisper_weights_quantization_and_position_offset() -> None:
    class Loader:
        pass

    class WhisperLoader:
        pass

    default_quantization = object()
    other_quantization = object()
    _install_numpy_loader_overrides(
        SimpleNamespace(Conv1D=_Conv1D),
        Loader,
        WhisperLoader,
        default_quantization,
    )

    linear_module = _Conv1D()
    linear_module.weight = _Tensor([[1, 2], [3, 4]])
    linear_module.bias = _Tensor([5, 6])
    linear_spec = SimpleNamespace()
    Loader().set_linear(linear_spec, linear_module, default_quantization)
    assert linear_spec.weight.tolist() == [[1, 3], [2, 4]]
    assert linear_spec.bias.tolist() == [5, 6]
    assert not np.shares_memory(linear_spec.weight, linear_module.weight.values)

    quantized_module = SimpleNamespace(
        qweight=_Tensor([[7]]),
        scales=_Tensor([8]),
        qzeros=_Tensor([9]),
        bias=None,
    )
    quantized_spec = SimpleNamespace()
    Loader().set_linear(quantized_spec, quantized_module, other_quantization)
    assert quantized_spec.weight.tolist() == [[7]]
    assert quantized_spec.weight_scale.tolist() == [8]
    assert quantized_spec.weight_zero.tolist() == [9]

    convolution = SimpleNamespace(weight=_Tensor([[10]]), bias=_Tensor([11]))
    convolution_spec = SimpleNamespace()
    WhisperLoader().set_conv1d(convolution_spec, convolution)
    assert convolution_spec.weight.tolist() == [[10]]
    assert convolution_spec.bias.tolist() == [11]

    position_spec = SimpleNamespace()
    position_module = SimpleNamespace(
        weight=_Tensor([[1], [2], [3]]), offset=1
    )
    Loader().set_position_encodings(position_spec, position_module)
    assert position_spec.encodings.tolist() == [[2], [3]]
