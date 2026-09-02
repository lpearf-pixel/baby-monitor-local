from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from packages.contracts.offline_application_rehearsal import (
    EvidenceResult,
    HistoricalEvidenceV1,
)


@dataclass(frozen=True)
class HistoricalEvidenceSummary:
    items: tuple[HistoricalEvidenceV1, ...]
    counts: Mapping[EvidenceResult, int]


def summarize_historical_evidence(
    items: tuple[HistoricalEvidenceV1, ...],
) -> HistoricalEvidenceSummary:
    counts = Counter(item.result for item in items)
    return HistoricalEvidenceSummary(
        items=items,
        counts=MappingProxyType(dict(counts)),
    )


__all__ = ["HistoricalEvidenceSummary", "summarize_historical_evidence"]
