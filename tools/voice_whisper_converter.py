from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any


PINNED_PACKAGES = {
    "ctranslate2": "4.8.1",
    "numpy": "1.26.4",
    "pydantic": "2.13.4",
    "torch": "2.2.2",
    "transformers": "4.56.2",
}


def require_pinned_packages(
    version_reader: Callable[[str], str] = metadata.version,
) -> None:
    try:
        valid = all(
            version_reader(package) == expected
            for package, expected in PINNED_PACKAGES.items()
        )
    except Exception as error:
        raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE") from error
    if not valid:
        raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE")


def _array(value: Any) -> Any:
    return value.detach().cpu().numpy().copy()


def _install_numpy_loader_overrides(
    transformers: Any,
    model_loader: Any,
    whisper_loader: Any,
    default_quantization: Any,
) -> None:
    def set_linear(
        _self: Any,
        spec: Any,
        module: Any,
        quant_type: Any = default_quantization,
    ) -> None:
        if quant_type == default_quantization:
            weight = module.weight
        else:
            weight = module.qweight
            spec.weight_scale = _array(module.scales)
            spec.weight_zero = _array(module.qzeros)
        if isinstance(module, transformers.Conv1D):
            weight = weight.transpose(0, 1)
        spec.weight = _array(weight)
        if hasattr(module, "bias") and module.bias is not None:
            spec.bias = _array(module.bias)

    def set_layer_norm(_self: Any, spec: Any, module: Any) -> None:
        spec.gamma = _array(module.weight)
        spec.beta = _array(module.bias)

    def set_embeddings(_self: Any, spec: Any, module: Any) -> None:
        spec.weight = _array(module.weight)

    def set_position_encodings(_self: Any, spec: Any, module: Any) -> None:
        encodings = _array(module.weight)
        offset = getattr(module, "offset", 0)
        spec.encodings = encodings[offset:] if offset > 0 else encodings

    def set_conv1d(_self: Any, spec: Any, module: Any) -> None:
        spec.weight = _array(module.weight)
        spec.bias = _array(module.bias)

    model_loader.set_linear = set_linear
    model_loader.set_layer_norm = set_layer_norm
    model_loader.set_embeddings = set_embeddings
    model_loader.set_position_encodings = set_position_encodings
    whisper_loader.set_conv1d = set_conv1d


def _require_prefix(expected_prefix: Path) -> None:
    try:
        if (
            expected_prefix.is_symlink()
            or Path(sys.prefix).resolve(strict=True)
            != expected_prefix.resolve(strict=True)
        ):
            raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE")
    except OSError as error:
        raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE") from error


def convert(
    model: Path,
    output_dir: Path,
    copy_files: tuple[str, ...],
    expected_prefix: Path,
) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    require_pinned_packages()
    _require_prefix(expected_prefix)

    import transformers
    from ctranslate2.converters.transformers import (
        ModelLoader,
        TransformersConverter,
        WhisperLoader,
    )
    from ctranslate2.specs.common_spec import Quantization

    _install_numpy_loader_overrides(
        transformers, ModelLoader, WhisperLoader, Quantization.CT2
    )
    converter = TransformersConverter(str(model), copy_files=list(copy_files))
    converter.convert(str(output_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a verified local Whisper bundle")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--expected-prefix", type=Path, required=True)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output_dir", type=Path)
    parser.add_argument("--copy_files", nargs="+")
    arguments = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    require_pinned_packages()
    _require_prefix(arguments.expected_prefix)
    if arguments.check:
        if any(
            value is not None
            for value in (arguments.model, arguments.output_dir, arguments.copy_files)
        ):
            raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE")
        return 0
    if (
        arguments.model is None
        or arguments.output_dir is None
        or arguments.copy_files is None
    ):
        raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE")
    copy_files = tuple(arguments.copy_files)
    if copy_files != ("tokenizer.json", "preprocessor_config.json"):
        raise RuntimeError("VOICE_CONVERTER_UNAVAILABLE")
    convert(
        arguments.model,
        arguments.output_dir,
        copy_files,
        arguments.expected_prefix,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
