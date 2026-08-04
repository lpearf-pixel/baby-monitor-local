from __future__ import annotations

import stat
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from packages.monitoring.alpha_quality import (
    HealthResult,
    QualityConfigError,
    _atomic_write,
    _read_yaml_mapping,
    with_source_subtype,
)


@dataclass(frozen=True)
class ProbeAttempt:
    subtype: int
    code: str
    protocol: str = ""
    bytes_received: int = 0
    source_dimensions: tuple[int, int] | None = None


@dataclass(frozen=True)
class ProbeSummary:
    attempts: tuple[ProbeAttempt, ...]
    recommended_subtype: int | None
    backup: Path


@dataclass(frozen=True)
class ApplySummary:
    applied_subtype: int
    health: HealthResult
    original_config_restored: bool
    backup: Path


def _validated_candidates(candidates: Sequence[int]) -> tuple[int, ...]:
    values = tuple(candidates)
    if (
        not values
        or len(set(values)) != len(values)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in range(6)
            for value in values
        )
    ):
        raise QualityConfigError("INVALID_SUBTYPE_CANDIDATES")
    return values


def _recommended(attempts: list[ProbeAttempt]) -> int | None:
    passing = [
        attempt
        for attempt in attempts
        if attempt.code == "PASS" and attempt.source_dimensions is not None
    ]
    best = max(
        passing,
        key=lambda attempt: (
            attempt.source_dimensions[0] * attempt.source_dimensions[1]
        ),
        default=None,
    )
    return None if best is None else best.subtype


def probe_subtypes(
    config_path: Path,
    backups_dir: Path,
    candidates: Sequence[int],
    restart: Callable[[], None],
    health_check: Callable[[], HealthResult],
    now: datetime,
) -> ProbeSummary:
    candidate_values = _validated_candidates(candidates)
    original = _read_yaml_mapping(
        config_path,
        missing_code="SOURCE_NOT_CONFIGURED",
    )
    original_text = config_path.read_text(encoding="utf-8")
    original_mode = stat.S_IMODE(config_path.stat().st_mode)

    # Validate every transformation before creating a backup or restarting Alpha.
    transformed = [
        (subtype, with_source_subtype(original, subtype))
        for subtype in candidate_values
    ]

    backups_dir.mkdir(parents=True, exist_ok=True)
    backup = backups_dir / (
        f"go2rtc-subtype-probe-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    )
    backup.write_text(original_text, encoding="utf-8")
    backup.chmod(original_mode)

    attempts: list[ProbeAttempt] = []
    try:
        for subtype, candidate_config in transformed:
            rendered = yaml.safe_dump(
                candidate_config,
                sort_keys=False,
                allow_unicode=True,
            )
            _atomic_write(config_path, rendered, original_mode)
            restart()
            result = health_check()
            attempts.append(
                ProbeAttempt(
                    subtype=subtype,
                    code=result.code,
                    protocol=result.protocol,
                    bytes_received=result.bytes_received,
                    source_dimensions=result.source_dimensions,
                )
            )
    finally:
        # A successful scan is observational: applying its recommendation is a
        # separate operation. This also restores the exact bytes after failures
        # and KeyboardInterrupt.
        _atomic_write(config_path, original_text, original_mode)
        restart()

    return ProbeSummary(
        attempts=tuple(attempts),
        recommended_subtype=_recommended(attempts),
        backup=backup,
    )


def apply_subtype(
    config_path: Path,
    backups_dir: Path,
    subtype: int,
    minimum_dimensions: tuple[int, int],
    restart: Callable[[], None],
    health_check: Callable[[], HealthResult],
    now: datetime,
) -> ApplySummary:
    if isinstance(subtype, bool) or not isinstance(subtype, int) or subtype not in range(6):
        raise QualityConfigError("INVALID_SUBTYPE")
    if (
        len(minimum_dimensions) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in minimum_dimensions
        )
    ):
        raise QualityConfigError("INVALID_SOURCE_DIMENSIONS")

    original = _read_yaml_mapping(
        config_path,
        missing_code="SOURCE_NOT_CONFIGURED",
    )
    original_text = config_path.read_text(encoding="utf-8")
    original_mode = stat.S_IMODE(config_path.stat().st_mode)
    updated = with_source_subtype(original, subtype)

    backups_dir.mkdir(parents=True, exist_ok=True)
    backup = backups_dir / (
        f"go2rtc-quality-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    )
    backup.write_text(original_text, encoding="utf-8")
    backup.chmod(original_mode)

    rendered = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
    keep_updated = False
    try:
        _atomic_write(config_path, rendered, original_mode)
        restart()
        health = health_check()
        dimensions = health.source_dimensions
        if health.code == "PASS" and (
            dimensions is None
            or dimensions[0] < minimum_dimensions[0]
            or dimensions[1] < minimum_dimensions[1]
        ):
            health = HealthResult(
                code="SOURCE_DIMENSIONS_TOO_LOW",
                protocol=health.protocol,
                bytes_received=health.bytes_received,
                source_dimensions=health.source_dimensions,
                live_dimensions=health.live_dimensions,
            )

        keep_updated = health.code == "PASS"
        return ApplySummary(
            applied_subtype=subtype,
            health=health,
            original_config_restored=not keep_updated,
            backup=backup,
        )
    finally:
        if not keep_updated:
            _atomic_write(config_path, original_text, original_mode)
            restart()
