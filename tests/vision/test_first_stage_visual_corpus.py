from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.contracts.visual_corpus import ScenarioId
from services.vision.corpus_manifest import load_manifest, validate_first_stage


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "visual_corpus"


def test_tracked_first_stage_manifest_is_complete() -> None:
    manifest = load_manifest(FIXTURE_ROOT / "manifest.json")

    if manifest.readiness == "PARTIAL":
        observed = {
            scenario for clip in manifest.clips for scenario in clip.scenario_ids
        }
        assert set(ScenarioId) - observed == {
            ScenarioId.WIDE_02,
            ScenarioId.OCC_03,
            ScenarioId.NEG_01,
            ScenarioId.NEG_02,
        }
        assert {
            clip.labels.wide_content_role
            for clip in manifest.clips
            if clip.labels.framing in {"crib_wide", "room_wide"}
        } == {"infant_small", "adult_present_or_entering"}
        pytest.skip("visual_corpus_first_stage_incomplete")

    validate_first_stage(manifest)

    assert 10 <= len(manifest.clips) <= 20
    assert sum(
        clip.labels.framing in {"crib_wide", "room_wide"}
        and clip.source_type in {"REAL", "PUBLIC_DATASET"}
        for clip in manifest.clips
    ) >= 3


def test_tracked_corpus_contains_no_media_files() -> None:
    media_suffixes = {
        ".avi",
        ".jpeg",
        ".jpg",
        ".mkv",
        ".mov",
        ".mp4",
        ".ogv",
        ".png",
        ".webm",
    }

    assert [
        path
        for path in FIXTURE_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in media_suffixes
    ] == []


def test_source_ledger_matches_manifest_and_never_embeds_media() -> None:
    manifest = load_manifest(FIXTURE_ROOT / "manifest.json")
    licenses = json.loads(
        (FIXTURE_ROOT / "source" / "licenses.json").read_text(encoding="utf-8")
    )
    checksums = json.loads(
        (FIXTURE_ROOT / "source" / "checksums.json").read_text(encoding="utf-8")
    )

    manifest_ids = {source.source_id for source in manifest.sources}
    assert {source["source_id"] for source in licenses["sources"]} == manifest_ids
    assert {source["source_id"] for source in checksums["sources"]} == manifest_ids
    assert all(source.local_only for source in manifest.sources)
    assert all(not source.github_allowed for source in manifest.sources)
