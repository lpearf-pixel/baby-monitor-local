from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


class ModelAssetCode(StrEnum):
    OK = "ok"
    MISSING = "missing"
    SIZE_MISMATCH = "size_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    DOWNLOAD_FAILED = "download_failed"


@dataclass(frozen=True)
class ModelAsset:
    filename: str
    url: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.filename)
        parsed = urlsplit(self.url)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.name
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or self.size <= 0
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("invalid_realtime_model_manifest")


@dataclass(frozen=True)
class ModelAssetStatus:
    code: ModelAssetCode
    checked_count: int = 0


MODEL_ROOT_NAME = "openvino-2025.4.1"
REALTIME_MODEL_ASSETS = (
    ModelAsset(
        filename="face_detection_yunet_2023mar.onnx",
        url=(
            "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/"
            "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
        ),
        size=232_589,
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    ModelAsset(
        filename="human-pose-estimation-0001.xml",
        url=(
            "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
            "2023.0/models_bin/1/human-pose-estimation-0001/FP16/"
            "human-pose-estimation-0001.xml"
        ),
        size=218_215,
        sha256="ebd70031f92e52b7f1d6ef3b1aead6eff0c9c52130e65ecf77a2447b90a32b84",
    ),
    ModelAsset(
        filename="human-pose-estimation-0001.bin",
        url=(
            "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
            "2023.0/models_bin/1/human-pose-estimation-0001/FP16/"
            "human-pose-estimation-0001.bin"
        ),
        size=8_197_354,
        sha256="fd4604233dd9ca09fba51c098b662e5fe6b03bf5dac174b686c3d6d5977cf8d5",
    ),
)


ModelFetcher = Callable[[str, int], bytes]


def verify_realtime_model_assets(
    root: Path,
    *,
    manifest: tuple[ModelAsset, ...] = REALTIME_MODEL_ASSETS,
) -> ModelAssetStatus:
    checked = 0
    for asset in manifest:
        target = root / asset.filename
        try:
            stat = target.stat()
        except OSError:
            return ModelAssetStatus(ModelAssetCode.MISSING, checked)
        if not target.is_file():
            return ModelAssetStatus(ModelAssetCode.MISSING, checked)
        if stat.st_size != asset.size:
            return ModelAssetStatus(ModelAssetCode.SIZE_MISMATCH, checked)
        try:
            digest = _digest_file(target)
        except OSError:
            return ModelAssetStatus(ModelAssetCode.MISSING, checked)
        if digest != asset.sha256:
            return ModelAssetStatus(ModelAssetCode.DIGEST_MISMATCH, checked)
        checked += 1
    return ModelAssetStatus(ModelAssetCode.OK, checked)


def install_realtime_model_assets(
    root: Path,
    *,
    manifest: tuple[ModelAsset, ...] = REALTIME_MODEL_ASSETS,
    fetcher: ModelFetcher | None = None,
) -> ModelAssetStatus:
    read = fetcher or _fetch_https
    for asset in manifest:
        try:
            payload = read(asset.url, asset.size + 1)
        except Exception:
            return ModelAssetStatus(ModelAssetCode.DOWNLOAD_FAILED)
        if len(payload) != asset.size:
            return ModelAssetStatus(ModelAssetCode.SIZE_MISMATCH)
        if sha256(payload).hexdigest() != asset.sha256:
            return ModelAssetStatus(ModelAssetCode.DIGEST_MISMATCH)

        target = root / asset.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".partial",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
            temporary_name = None
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)
    return verify_realtime_model_assets(root, manifest=manifest)


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch_https(url: str, maximum: int) -> bytes:
    opener = build_opener(ProxyHandler({}))
    request = Request(url, headers={"Accept": "application/octet-stream"})
    with opener.open(request, timeout=60) as response:
        final_url = response.geturl()
        if urlsplit(final_url).scheme != "https":
            raise ValueError("realtime_model_download_failed")
        payload = response.read(maximum)
    return payload
