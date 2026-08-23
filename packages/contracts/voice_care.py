"""Strict vendored Baby Care Voice Care v1 contracts.

The JSON Schema and golden corpus are copied byte-for-byte from one immutable Baby
Care commit. Runtime code never imports or downloads from another checkout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)


VOICE_CARE_CONTRACT_INVALID = "VOICE_CARE_CONTRACT_INVALID"
BABY_CARE_SOURCE_REPOSITORY = "lpearf-pixel/baby-care"
BABY_CARE_SOURCE_COMMIT = "bb1337226c1948695159d14199c9bb73cdaf115a"
VOICE_CARE_SCHEMA_SHA256 = "44e4648765e1d3df8419d45fe87a5b835b8e21c217ee9da699b08dfcc974b0de"
VOICE_CARE_CORPUS_SHA256 = "af0736f02011225e38054336c7ca472a8e0e9b6dde600ae6f62540886fea06e5"
_CONTRACT_DIRECTORY = Path(__file__).with_name("voice-care")
_SCHEMA_FILE = "voice-care-intent.v1.schema.json"
_CORPUS_FILE = "voice-care-v1.json"
_SOURCE_FILE = "baby-care-source-commit.txt"
_MAX_ARTIFACT_BYTES = 1_048_576


def _require_timezone(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError(VOICE_CARE_CONTRACT_INVALID)
    return value

SafePositiveInteger: TypeAlias = Annotated[int, Field(strict=True, gt=0, le=9_007_199_254_740_991)]
OffsetDateTime: TypeAlias = Annotated[datetime, AfterValidator(_require_timezone)]
ModelVersion: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$"),
]
Signature: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-]{85}[AQgw]$"),
]
Digest: TypeAlias = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
LiquidType: TypeAlias = Literal["expressed_breast_milk", "formula"]
SpeakerState: TypeAlias = Literal[
    "verified", "uncertain", "mismatch", "not_enrolled", "unavailable"
]
WarningCode: TypeAlias = Literal[
    "possible_duplicate", "unusual_value", "sleep_overlap", "old_backfill"
]


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FeedingStartPayload(_ContractModel):
    mode: Literal["unknown", "bottle", "direct_breastfeeding"]
    startedAt: OffsetDateTime


class UnknownProposal(_ContractModel):
    mode: Literal["unknown"]
    startedAt: OffsetDateTime
    endedAt: None


class BottleProposal(_ContractModel):
    mode: Literal["bottle"]
    startedAt: OffsetDateTime
    endedAt: OffsetDateTime | None
    liquidType: LiquidType | None
    amountMl: SafePositiveInteger | None
    bottleCapacityMl: SafePositiveInteger | None


class DirectProposal(_ContractModel):
    mode: Literal["direct_breastfeeding"]
    startedAt: OffsetDateTime
    endedAt: OffsetDateTime | None
    durationMinutes: SafePositiveInteger | None


class FeedingUpdatePayload(_ContractModel):
    expectedVersion: SafePositiveInteger
    proposal: UnknownProposal | BottleProposal | DirectProposal = Field(discriminator="mode")


class BottleFinalProposal(_ContractModel):
    mode: Literal["bottle"]
    startedAt: OffsetDateTime
    endedAt: OffsetDateTime
    liquidType: LiquidType
    amountMl: SafePositiveInteger
    bottleCapacityMl: SafePositiveInteger | None


class DirectFinalProposal(_ContractModel):
    mode: Literal["direct_breastfeeding"]
    startedAt: OffsetDateTime
    endedAt: OffsetDateTime
    durationMinutes: SafePositiveInteger


class FeedingEndPayload(_ContractModel):
    expectedVersion: SafePositiveInteger
    finalProposal: BottleFinalProposal | DirectFinalProposal = Field(discriminator="mode")


class CareConfirmPayload(_ContractModel):
    proposalDigest: Digest
    expectedVersion: SafePositiveInteger
    warningDigest: Digest | None
    confirmedWarningCodes: Annotated[list[WarningCode], Field(max_length=4)]

    @model_validator(mode="after")
    def warning_set_requires_digest(self) -> "CareConfirmPayload":
        if self.confirmedWarningCodes and self.warningDigest is None:
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        return self


class CareCancelPayload(_ContractModel):
    expectedVersion: SafePositiveInteger
    reason: Literal["caregiver_cancelled", "duplicate", "incorrect_intent", "stale"]


class _VoiceCareEnvelope(_ContractModel):
    schemaVersion: Literal[1]
    requestId: UUID
    deviceId: UUID
    leaseId: UUID
    issuedAt: OffsetDateTime
    occurredAt: OffsetDateTime
    deliveryMode: Literal["live", "replay"]
    speakerState: SpeakerState
    source: Literal["voice"]
    modelVersion: ModelVersion
    signature: Signature


class FeedingStartIntent(_VoiceCareEnvelope):
    intentType: Literal["feeding_start"]
    careSessionId: None
    payload: FeedingStartPayload


class FeedingUpdateIntent(_VoiceCareEnvelope):
    intentType: Literal["feeding_update"]
    careSessionId: UUID
    payload: FeedingUpdatePayload


class FeedingEndIntent(_VoiceCareEnvelope):
    intentType: Literal["feeding_end"]
    careSessionId: UUID
    payload: FeedingEndPayload


class CareConfirmIntent(_VoiceCareEnvelope):
    intentType: Literal["care_confirm"]
    careSessionId: UUID
    payload: CareConfirmPayload


class CareCancelIntent(_VoiceCareEnvelope):
    intentType: Literal["care_cancel"]
    careSessionId: UUID
    payload: CareCancelPayload


VoiceCareIntentV1: TypeAlias = Annotated[
    FeedingStartIntent
    | FeedingUpdateIntent
    | FeedingEndIntent
    | CareConfirmIntent
    | CareCancelIntent,
    Field(discriminator="intentType"),
]
_VOICE_CARE_ADAPTER = TypeAdapter(VoiceCareIntentV1)


@dataclass(frozen=True)
class VendoredVoiceCareContract:
    source_commit: str
    schema_sha256: str
    corpus_sha256: str


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        value[key] = item
    return value


def parse_voice_care_intent(raw: str | bytes) -> VoiceCareIntentV1:
    """Parse only canonical UTF-8 Voice Care v1 JSON with no duplicate keys."""

    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        if not isinstance(text, str) or not text or text != text.strip():
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if canonical != text:
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        return _VOICE_CARE_ADAPTER.validate_json(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError, TypeError):
        raise ValueError(VOICE_CARE_CONTRACT_INVALID) from None


def verify_vendored_voice_care_contract(
    directory: Path = _CONTRACT_DIRECTORY,
) -> VendoredVoiceCareContract:
    """Verify exact committed bytes without following symlinks or leaving the package."""

    try:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        canonical_directory = directory.resolve(strict=True)
        values: dict[str, bytes] = {}
        for filename in (_SCHEMA_FILE, _CORPUS_FILE, _SOURCE_FILE):
            path = directory / filename
            stat = path.lstat()
            if path.is_symlink() or not path.is_file() or not 0 < stat.st_size <= _MAX_ARTIFACT_BYTES:
                raise ValueError(VOICE_CARE_CONTRACT_INVALID)
            canonical = path.resolve(strict=True)
            if canonical.parent != canonical_directory:
                raise ValueError(VOICE_CARE_CONTRACT_INVALID)
            values[filename] = path.read_bytes()
        source_commit = values[_SOURCE_FILE].decode("ascii")
        if source_commit != f"{BABY_CARE_SOURCE_COMMIT}\n":
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        schema_sha256 = hashlib.sha256(values[_SCHEMA_FILE]).hexdigest()
        corpus_sha256 = hashlib.sha256(values[_CORPUS_FILE]).hexdigest()
        if schema_sha256 != VOICE_CARE_SCHEMA_SHA256 or corpus_sha256 != VOICE_CARE_CORPUS_SHA256:
            raise ValueError(VOICE_CARE_CONTRACT_INVALID)
        return VendoredVoiceCareContract(
            source_commit=BABY_CARE_SOURCE_COMMIT,
            schema_sha256=schema_sha256,
            corpus_sha256=corpus_sha256,
        )
    except (OSError, UnicodeDecodeError, ValueError):
        raise ValueError(VOICE_CARE_CONTRACT_INVALID) from None


__all__ = [
    "BABY_CARE_SOURCE_COMMIT",
    "BABY_CARE_SOURCE_REPOSITORY",
    "VOICE_CARE_CONTRACT_INVALID",
    "VOICE_CARE_CORPUS_SHA256",
    "VOICE_CARE_SCHEMA_SHA256",
    "VoiceCareIntentV1",
    "VendoredVoiceCareContract",
    "parse_voice_care_intent",
    "verify_vendored_voice_care_contract",
]
