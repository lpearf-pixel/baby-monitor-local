from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.contracts.vision import (
    AdultPresence,
    BedState,
    FaceVisibility,
    ImageQuality,
    ModelRisk,
    Posture,
    RiskSnapshot,
    RiskTransition,
    RiskTransitionKind,
    VisualReview,
    VisualRiskKind,
    VisualRiskState,
)


MINIMUM_CONFIDENCE = 0.70
MINIMUM_CONFIRMATION_SECONDS = 10


@dataclass
class _RiskTrack:
    state: VisualRiskState = VisualRiskState.NORMAL
    candidate_first_at: datetime | None = None
    candidate_count: int = 0
    recovery_first_at: datetime | None = None
    recovery_count: int = 0

    def clear_candidate_evidence(self) -> None:
        self.candidate_first_at = None
        self.candidate_count = 0

    def clear_recovery_evidence(self) -> None:
        self.recovery_first_at = None
        self.recovery_count = 0


class VisualRiskStateMachine:
    def __init__(self) -> None:
        self._tracks = {risk: _RiskTrack() for risk in VisualRiskKind}
        self._last_observed_at: datetime | None = None
        self._adult_present = False

    def state_for(self, risk_kind: VisualRiskKind) -> VisualRiskState:
        return self._tracks[risk_kind].state

    def snapshot(self, snapshot_at: datetime) -> RiskSnapshot:
        self._require_monotonic_aware_time(snapshot_at)
        return RiskSnapshot(
            snapshot_at=snapshot_at,
            open_risks=frozenset(
                risk_kind
                for risk_kind, track in self._tracks.items()
                if track.state is VisualRiskState.ALERT
            ),
        )

    @classmethod
    def from_snapshot(cls, snapshot: RiskSnapshot) -> "VisualRiskStateMachine":
        machine = cls()
        for risk_kind in snapshot.open_risks:
            machine._tracks[risk_kind].state = VisualRiskState.ALERT
        machine._last_observed_at = snapshot.snapshot_at
        return machine

    def evaluate(
        self, review: VisualReview, observed_at: datetime
    ) -> tuple[RiskTransition, ...]:
        self._require_monotonic_aware_time(observed_at)
        transitions: list[RiskTransition] = []

        adult_present = review.adult_presence is AdultPresence.PRESENT
        if adult_present and not self._adult_present:
            overall = self._overall_state()
            transitions.append(
                RiskTransition(
                    transition_kind=RiskTransitionKind.ADULT_INTERVENTION,
                    risk_kind=None,
                    previous_state=overall,
                    current_state=overall,
                    observed_at=observed_at,
                    confidence=review.confidence,
                    notify=False,
                )
            )
        if review.adult_presence is AdultPresence.ABSENT:
            self._adult_present = False
        elif adult_present:
            self._adult_present = True

        for risk_kind in VisualRiskKind:
            candidate, safe = self._evidence_for(
                risk_kind,
                review,
            )
            transition = self._advance_track(
                risk_kind=risk_kind,
                candidate=candidate,
                valid_candidate=candidate
                and review.confidence >= MINIMUM_CONFIDENCE,
                safe=safe,
                observed_at=observed_at,
                confidence=review.confidence,
            )
            if transition is not None:
                transitions.append(transition)

        self._last_observed_at = observed_at
        return tuple(transitions)

    def _require_monotonic_aware_time(self, observed_at: datetime) -> None:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self._last_observed_at is not None and observed_at < self._last_observed_at:
            raise ValueError("observed_at must be monotonic")

    def _overall_state(self) -> VisualRiskState:
        states = {track.state for track in self._tracks.values()}
        if VisualRiskState.ALERT in states:
            return VisualRiskState.ALERT
        if VisualRiskState.WATCH in states:
            return VisualRiskState.WATCH
        return VisualRiskState.NORMAL

    @staticmethod
    def _evidence_for(
        risk_kind: VisualRiskKind,
        review: VisualReview,
    ) -> tuple[bool, bool]:
        if risk_kind is VisualRiskKind.FACE_NOT_VISIBLE:
            candidate = (
                review.face_visibility is FaceVisibility.NOT_VISIBLE
                and review.risk is ModelRisk.HIGH
            )
            explicit_safe = review.face_visibility is FaceVisibility.CLEAR
        elif risk_kind is VisualRiskKind.PRONE_CANDIDATE:
            candidate = (
                review.posture is Posture.PRONE_CANDIDATE
                and review.risk is ModelRisk.HIGH
            )
            explicit_safe = review.posture in {
                Posture.SUPINE,
                Posture.SIDE,
                Posture.UPRIGHT,
            }
        else:
            candidate = review.bed_state is BedState.OUTSIDE_CANDIDATE
            explicit_safe = review.bed_state is BedState.INSIDE

        safe = (
            explicit_safe
            and review.adult_presence is AdultPresence.ABSENT
            and review.image_quality is ImageQuality.USABLE
            and review.confidence >= MINIMUM_CONFIDENCE
        )
        return candidate, safe

    def _advance_track(
        self,
        *,
        risk_kind: VisualRiskKind,
        candidate: bool,
        valid_candidate: bool,
        safe: bool,
        observed_at: datetime,
        confidence: float,
    ) -> RiskTransition | None:
        track = self._tracks[risk_kind]

        if track.state is VisualRiskState.ALERT:
            track.clear_candidate_evidence()
            if not safe:
                track.clear_recovery_evidence()
                return None
            self._record_recovery_evidence(track, observed_at)
            if not self._evidence_is_confirmed(
                track.recovery_first_at,
                track.recovery_count,
                observed_at,
            ):
                return None
            previous = track.state
            self._reset_track(track)
            return self._transition(
                kind=RiskTransitionKind.RECOVERED,
                risk_kind=risk_kind,
                previous=previous,
                current=VisualRiskState.NORMAL,
                observed_at=observed_at,
                confidence=confidence,
                notify=True,
            )

        if candidate:
            track.clear_recovery_evidence()
            previous = track.state
            if track.state is VisualRiskState.NORMAL:
                track.state = VisualRiskState.WATCH
            if not valid_candidate:
                track.clear_candidate_evidence()
                if previous is VisualRiskState.NORMAL:
                    return self._transition(
                        kind=RiskTransitionKind.WATCH_STARTED,
                        risk_kind=risk_kind,
                        previous=previous,
                        current=track.state,
                        observed_at=observed_at,
                        confidence=confidence,
                        notify=False,
                    )
                return None

            self._record_candidate_evidence(track, observed_at)
            if self._evidence_is_confirmed(
                track.candidate_first_at,
                track.candidate_count,
                observed_at,
            ):
                previous = track.state
                track.state = VisualRiskState.ALERT
                track.clear_candidate_evidence()
                return self._transition(
                    kind=RiskTransitionKind.ALERT_OPENED,
                    risk_kind=risk_kind,
                    previous=previous,
                    current=track.state,
                    observed_at=observed_at,
                    confidence=confidence,
                    notify=True,
                )
            if previous is VisualRiskState.NORMAL:
                return self._transition(
                    kind=RiskTransitionKind.WATCH_STARTED,
                    risk_kind=risk_kind,
                    previous=previous,
                    current=track.state,
                    observed_at=observed_at,
                    confidence=confidence,
                    notify=False,
                )
            return None

        track.clear_candidate_evidence()
        if track.state is not VisualRiskState.WATCH:
            track.clear_recovery_evidence()
            return None
        if not safe:
            track.clear_recovery_evidence()
            return None

        self._record_recovery_evidence(track, observed_at)
        if not self._evidence_is_confirmed(
            track.recovery_first_at,
            track.recovery_count,
            observed_at,
        ):
            return None
        previous = track.state
        self._reset_track(track)
        return self._transition(
            kind=RiskTransitionKind.WATCH_CLEARED,
            risk_kind=risk_kind,
            previous=previous,
            current=VisualRiskState.NORMAL,
            observed_at=observed_at,
            confidence=confidence,
            notify=False,
        )

    @staticmethod
    def _record_candidate_evidence(track: _RiskTrack, observed_at: datetime) -> None:
        if track.candidate_first_at is None:
            track.candidate_first_at = observed_at
            track.candidate_count = 1
        else:
            track.candidate_count += 1

    @staticmethod
    def _record_recovery_evidence(track: _RiskTrack, observed_at: datetime) -> None:
        if track.recovery_first_at is None:
            track.recovery_first_at = observed_at
            track.recovery_count = 1
        else:
            track.recovery_count += 1

    @staticmethod
    def _evidence_is_confirmed(
        first_at: datetime | None,
        count: int,
        observed_at: datetime,
    ) -> bool:
        return (
            first_at is not None
            and count >= 2
            and (observed_at - first_at).total_seconds()
            >= MINIMUM_CONFIRMATION_SECONDS
        )

    @staticmethod
    def _reset_track(track: _RiskTrack) -> None:
        track.state = VisualRiskState.NORMAL
        track.clear_candidate_evidence()
        track.clear_recovery_evidence()

    @staticmethod
    def _transition(
        *,
        kind: RiskTransitionKind,
        risk_kind: VisualRiskKind,
        previous: VisualRiskState,
        current: VisualRiskState,
        observed_at: datetime,
        confidence: float,
        notify: bool,
    ) -> RiskTransition:
        return RiskTransition(
            transition_kind=kind,
            risk_kind=risk_kind,
            previous_state=previous,
            current_state=current,
            observed_at=observed_at,
            confidence=confidence,
            notify=notify,
        )
