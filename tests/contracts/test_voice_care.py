from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.contracts.voice_care import (
    BABY_CARE_SOURCE_COMMIT,
    VOICE_CARE_CORPUS_SHA256,
    VOICE_CARE_SCHEMA_SHA256,
    parse_voice_care_intent,
    verify_vendored_voice_care_contract,
)


CONTRACT_ROOT = Path(__file__).parents[2] / "packages" / "contracts" / "voice-care"


def test_vendored_contract_has_exact_source_identity_and_hashes() -> None:
    result = verify_vendored_voice_care_contract()
    assert result.source_commit == BABY_CARE_SOURCE_COMMIT
    assert result.schema_sha256 == VOICE_CARE_SCHEMA_SHA256
    assert result.corpus_sha256 == VOICE_CARE_CORPUS_SHA256
    assert (CONTRACT_ROOT / "baby-care-source-commit.txt").read_text(
        encoding="ascii"
    ) == f"{BABY_CARE_SOURCE_COMMIT}\n"


def test_all_exact_golden_corpus_examples_match_the_python_contract() -> None:
    corpus = json.loads(
        (CONTRACT_ROOT / "voice-care-v1.json").read_text(encoding="utf-8")
    )
    assert corpus["schemaId"] == "voice-care-intent.v1"
    assert len(corpus["valid"]) == 5
    assert len(corpus["invalid"]) >= 10
    for example in corpus["valid"]:
        assert parse_voice_care_intent(example["raw"]).intentType == example["name"].replace(
            "-", "_"
        )
    for example in corpus["invalid"]:
        with pytest.raises(ValueError, match="VOICE_CARE_CONTRACT_INVALID"):
            parse_voice_care_intent(example["raw"])


def test_contract_rejects_unknown_identity_and_private_content_fields() -> None:
    corpus = json.loads(
        (CONTRACT_ROOT / "voice-care-v1.json").read_text(encoding="utf-8")
    )
    valid = json.loads(corpus["valid"][0]["raw"])
    for forbidden in ("familyId", "babyId", "actorId", "transcript", "audio"):
        candidate = {**valid, forbidden: "private"}
        raw = json.dumps(
            candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with pytest.raises(ValueError, match="VOICE_CARE_CONTRACT_INVALID"):
            parse_voice_care_intent(raw)


def test_contract_rejects_noncanonical_or_duplicate_json() -> None:
    corpus = json.loads(
        (CONTRACT_ROOT / "voice-care-v1.json").read_text(encoding="utf-8")
    )
    valid = corpus["valid"][0]["raw"]
    for raw in (f" {valid}", valid.replace('"schemaVersion":1', '"schemaVersion":1,"schemaVersion":1', 1)):
        with pytest.raises(ValueError, match="VOICE_CARE_CONTRACT_INVALID"):
            parse_voice_care_intent(raw)


def test_contract_rejects_timestamp_without_required_offset() -> None:
    corpus = json.loads(
        (CONTRACT_ROOT / "voice-care-v1.json").read_text(encoding="utf-8")
    )
    candidate = json.loads(corpus["valid"][0]["raw"])
    candidate["issuedAt"] = "2026-08-23T08:20:00"
    raw = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="VOICE_CARE_CONTRACT_INVALID"):
        parse_voice_care_intent(raw)
