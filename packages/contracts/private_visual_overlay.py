from __future__ import annotations

import ipaddress
import json
import math
import re
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from packages.contracts.visual_corpus import ScenarioId


MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_PRIVATE_ASSET_BYTES = 128 * 1024 * 1024


class PrivateVisualOverlayError(RuntimeError):
    """Stable, redacted private-overlay metadata failure."""


class PrivateOverlayContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrivateSourceType(StrEnum):
    PRIVATE_LOCAL_CAPTURE = "PRIVATE_LOCAL_CAPTURE"


class PrivateReviewState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class LocalOverlayReadiness(StrEnum):
    LOCAL_UNAVAILABLE = "LOCAL_UNAVAILABLE"
    LOCAL_PARTIAL = "LOCAL_PARTIAL"
    LOCAL_READY = "LOCAL_READY"


class PrivateAssetMetadata(PrivateOverlayContract):
    private_asset_id: str = Field(pattern=r"^plc-[0-9a-f]{32}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_PRIVATE_ASSET_BYTES, strict=True)
    duration_ms: int = Field(ge=10_000, le=60_000, strict=True)
    codec: Literal["hevc", "h264", "mjpeg"]
    width: int = Field(ge=1, le=4096, strict=True)
    height: int = Field(ge=1, le=2160, strict=True)
    fps: float = Field(gt=0, le=120, allow_inf_nan=False, strict=True)
    scenario_ids: tuple[ScenarioId, ...] = Field(min_length=1, max_length=5)
    authorization_review: PrivateReviewState
    privacy_review: PrivateReviewState

    @field_validator("fps")
    @classmethod
    def require_finite_fps(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("fps must be finite")
        return value

    @model_validator(mode="after")
    def require_unique_scenarios(self) -> "PrivateAssetMetadata":
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must be unique")
        return self


class PrivateOverlayDescriptor(PrivateOverlayContract):
    schema_version: Literal[1] = 1
    source_type: PrivateSourceType
    assets: tuple[PrivateAssetMetadata, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_unique_asset_identity(self) -> "PrivateOverlayDescriptor":
        asset_ids = [asset.private_asset_id for asset in self.assets]
        digests = [asset.sha256 for asset in self.assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("private_asset_id values must be unique")
        if len(set(digests)) != len(digests):
            raise ValueError("sha256 values must be unique")
        return self


def load_private_overlay_descriptor(path: Path) -> PrivateOverlayDescriptor:
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_DESCRIPTOR_BYTES + 1)
        if len(raw) > MAX_DESCRIPTOR_BYTES:
            raise PrivateVisualOverlayError("private_overlay_metadata_invalid")
        payload = json.loads(raw.decode("utf-8"))
        if _contains_forbidden_locator(payload):
            raise PrivateVisualOverlayError("private_overlay_forbidden_locator")
        return PrivateOverlayDescriptor.model_validate(payload)
    except PrivateVisualOverlayError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise PrivateVisualOverlayError("private_overlay_metadata_invalid") from exc


def canonical_private_overlay_bytes(value: PrivateOverlayDescriptor) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


_FORBIDDEN_KEYS = frozenset(
    {
        "absolute_path",
        "account",
        "camera_did",
        "camera_id",
        "camera_uri",
        "device_key",
        "file_url",
        "host",
        "hostname",
        "ip",
        "path",
        "port",
        "source_url",
        "token",
        "uri",
    }
)
_LOCATOR_PREFIXES = ("file:", "http:", "https:", "rtsp:", "xiaomi:", "miss:", "cs2:")
_HOSTNAME_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


def _contains_forbidden_locator(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_KEYS:
                return True
            if _contains_forbidden_locator(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_forbidden_locator(item) for item in value)
    if not isinstance(value, str):
        return False

    decoded = unquote(value).strip()
    lowered = decoded.casefold()
    if (
        lowered.startswith(_LOCATOR_PREFIXES)
        or "://" in lowered
        or "/" in decoded
        or "\\" in decoded
        or decoded in {".", ".."}
        or lowered == "localhost"
        or _HOSTNAME_PATTERN.fullmatch(decoded) is not None
    ):
        return True
    try:
        ipaddress.ip_address(decoded.strip("[]"))
    except ValueError:
        return False
    return True


__all__ = [
    "LocalOverlayReadiness",
    "PrivateAssetMetadata",
    "PrivateOverlayDescriptor",
    "PrivateReviewState",
    "PrivateSourceType",
    "PrivateVisualOverlayError",
    "ScenarioId",
    "canonical_private_overlay_bytes",
    "load_private_overlay_descriptor",
]
