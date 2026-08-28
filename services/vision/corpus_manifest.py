from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.visual_corpus import (
    Framing,
    RecipeKind,
    ScenarioId,
    SourceType,
    VisualCorpusManifest,
    WideContentRole,
)


class VisualCorpusManifestError(RuntimeError):
    """A stable, redacted manifest failure."""


def load_manifest(path: Path) -> VisualCorpusManifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return VisualCorpusManifest.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise VisualCorpusManifestError("visual_corpus_manifest_invalid") from exc


def canonical_manifest_bytes(manifest: VisualCorpusManifest) -> bytes:
    return json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def canonical_manifest_digest(manifest: VisualCorpusManifest) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def validate_first_stage(manifest: VisualCorpusManifest) -> None:
    if not 10 <= len(manifest.clips) <= 20:
        raise ValueError("visual_corpus_clip_count_invalid")

    required = frozenset(ScenarioId)
    observed = frozenset(
        scenario
        for clip in manifest.clips
        for scenario in clip.scenario_ids
    )
    if not required.issubset(observed):
        raise ValueError("visual_corpus_scenario_missing")

    real_wide = tuple(
        clip
        for clip in manifest.clips
        if clip.labels.framing in {Framing.CRIB_WIDE, Framing.ROOM_WIDE}
        and clip.source_type in {SourceType.REAL, SourceType.PUBLIC_DATASET}
        and clip.recipe.kind is RecipeKind.SOURCE_SEGMENT
    )
    required_roles = {
        WideContentRole.INFANT_SMALL,
        WideContentRole.EMPTY_OR_OBJECT_ONLY,
        WideContentRole.ADULT_PRESENT_OR_ENTERING,
    }
    observed_roles = {clip.labels.wide_content_role for clip in real_wide}
    if len(real_wide) < 3 or not required_roles.issubset(observed_roles):
        raise ValueError("visual_corpus_real_wide_required")
