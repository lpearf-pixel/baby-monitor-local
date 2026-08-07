from __future__ import annotations

import math
from dataclasses import dataclass

from packages.contracts.vision import (
    AdultTrack,
    BedSubjectTrack,
    HeadFaceState,
    RealtimeCandidateKind,
    RealtimeCandidateTransition,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
    SceneQuality,
)


WARMUP_SECONDS = 10.0
HISTORY_SECONDS = 10.0
ADULT_EXIT_SUPPRESSION_SECONDS = 30.0


@dataclass
class _CandidateTrack:
    evidence_since: float | None = None
    clear_since: float | None = None
    watch_open: bool = False
    cooldown_until: float = 0.0


class RealtimeCandidateStateMachine:
    def __init__(self) -> None:
        self._tracks = {kind: _CandidateTrack() for kind in RealtimeCandidateKind}
        self._started_at: float | None = None
        self._last_monotonic: float | None = None
        self._last_face_visible_at: float | None = None
        self._last_inside_at: float | None = None
        self._last_motion_at: float | None = None
        self._last_adult_at: float | None = None
        self._noise_mean = 0.0
        self._noise_deviation = 0.0

    def evaluate(
        self,
        observation: RealtimeObservation,
        *,
        monotonic_now: float,
    ) -> tuple[RealtimeCandidateTransition, ...]:
        self._require_monotonic(monotonic_now)
        if self._started_at is None:
            self._started_at = monotonic_now

        transitions: list[RealtimeCandidateTransition] = []
        obstructed = observation.scene_quality in {
            SceneQuality.DARK,
            SceneQuality.FLAT,
        }
        transition = self._advance(
            RealtimeCandidateKind.CAMERA_OBSTRUCTED,
            condition=obstructed,
            clear_condition=observation.scene_quality is SceneQuality.USABLE,
            open_seconds=2.0,
            clear_seconds=2.0,
            monotonic_now=monotonic_now,
        )
        if transition is not None:
            transitions.append(transition)

        semantic_ready = (
            monotonic_now - self._started_at >= WARMUP_SECONDS
            and observation.scene_quality is SceneQuality.USABLE
        )
        if not semantic_ready:
            self._update_noise(observation.motion_ratio)
            self._record_history(observation, monotonic_now)
            return tuple(transitions)

        motion_threshold = min(
            0.20,
            max(0.01, self._noise_mean + 3 * self._noise_deviation),
        )
        significant_motion = observation.motion_ratio >= motion_threshold
        if significant_motion:
            self._last_motion_at = monotonic_now
        else:
            self._update_noise(observation.motion_ratio)

        definitions = (
            (
                RealtimeCandidateKind.SIGNIFICANT_BED_MOTION,
                significant_motion,
                not significant_motion,
                0.6,
                2.0,
            ),
            (
                RealtimeCandidateKind.POSSIBLE_ROLLOVER_OR_PRONE,
                self._recent(self._last_motion_at, monotonic_now, 3.0)
                and observation.pose_count is not None
                and observation.pose_count >= 1
                and observation.head_face_state
                is HeadFaceState.TEMPORARILY_MISSING
                and self._recent(
                    self._last_face_visible_at,
                    monotonic_now,
                    HISTORY_SECONDS,
                ),
                observation.head_face_state is HeadFaceState.VISIBLE,
                1.0,
                2.0,
            ),
            (
                RealtimeCandidateKind.POSSIBLE_FACE_OBSTRUCTION,
                observation.pose_count is not None
                and observation.pose_count >= 1
                and observation.head_face_state
                is HeadFaceState.TEMPORARILY_MISSING
                and self._recent(
                    self._last_face_visible_at,
                    monotonic_now,
                    HISTORY_SECONDS,
                ),
                observation.head_face_state is HeadFaceState.VISIBLE,
                1.5,
                2.0,
            ),
            (
                RealtimeCandidateKind.POSSIBLE_EXIT,
                observation.pose_count is not None
                and observation.bed_subject_track
                in {BedSubjectTrack.BOUNDARY, BedSubjectTrack.MISSING}
                and significant_motion
                and self._recent(
                    self._last_inside_at,
                    monotonic_now,
                    HISTORY_SECONDS,
                )
                and not self._recent(
                    self._last_adult_at,
                    monotonic_now,
                    ADULT_EXIT_SUPPRESSION_SECONDS,
                ),
                observation.bed_subject_track is BedSubjectTrack.INSIDE,
                1.0,
                2.0,
            ),
            (
                RealtimeCandidateKind.ADULT_INTERVENTION,
                observation.adult_track is AdultTrack.INTERSECTING_BED,
                observation.adult_track is AdultTrack.ABSENT,
                0.6,
                2.0,
            ),
        )
        for kind, condition, clear_condition, open_seconds, clear_seconds in definitions:
            transition = self._advance(
                kind,
                condition=condition,
                clear_condition=clear_condition,
                open_seconds=open_seconds,
                clear_seconds=clear_seconds,
                monotonic_now=monotonic_now,
            )
            if transition is not None:
                transitions.append(transition)

        self._record_history(observation, monotonic_now)
        return tuple(transitions)

    def _advance(
        self,
        kind: RealtimeCandidateKind,
        *,
        condition: bool,
        clear_condition: bool,
        open_seconds: float,
        clear_seconds: float,
        monotonic_now: float,
    ) -> RealtimeCandidateTransition | None:
        track = self._tracks[kind]
        if condition:
            track.clear_since = None
            if track.watch_open or monotonic_now < track.cooldown_until:
                return None
            if track.evidence_since is None:
                track.evidence_since = monotonic_now
                return None
            if monotonic_now - track.evidence_since + 1e-9 < open_seconds:
                return None
            track.evidence_since = None
            track.watch_open = True
            return self._transition(
                RealtimeCandidateTransitionKind.WATCH_OPENED,
                kind,
                monotonic_now,
            )

        track.evidence_since = None
        if not track.watch_open:
            track.clear_since = None
            return None
        if not clear_condition:
            track.clear_since = None
            return None
        if track.clear_since is None:
            track.clear_since = monotonic_now
            return None
        if monotonic_now - track.clear_since + 1e-9 < clear_seconds:
            return None
        track.clear_since = None
        track.watch_open = False
        track.cooldown_until = monotonic_now + 2.0
        return self._transition(
            RealtimeCandidateTransitionKind.CANDIDATE_CLEARED,
            kind,
            monotonic_now,
        )

    def _record_history(
        self,
        observation: RealtimeObservation,
        monotonic_now: float,
    ) -> None:
        if observation.head_face_state is HeadFaceState.VISIBLE:
            self._last_face_visible_at = monotonic_now
        if observation.bed_subject_track is BedSubjectTrack.INSIDE:
            self._last_inside_at = monotonic_now
        if observation.adult_track is AdultTrack.INTERSECTING_BED:
            self._last_adult_at = monotonic_now

    def _update_noise(self, value: float) -> None:
        if value > 0.05:
            return
        difference = abs(value - self._noise_mean)
        self._noise_mean = 0.9 * self._noise_mean + 0.1 * value
        self._noise_deviation = 0.9 * self._noise_deviation + 0.1 * difference

    @staticmethod
    def _recent(value: float | None, now: float, seconds: float) -> bool:
        return value is not None and 0 <= now - value <= seconds

    @staticmethod
    def _transition(
        transition_kind: RealtimeCandidateTransitionKind,
        candidate_kind: RealtimeCandidateKind,
        monotonic_at: float,
    ) -> RealtimeCandidateTransition:
        return RealtimeCandidateTransition(
            transition_kind=transition_kind,
            candidate_kind=candidate_kind,
            monotonic_at=monotonic_at,
        )

    def _require_monotonic(self, value: float) -> None:
        if not math.isfinite(value) or value < 0:
            raise ValueError("monotonic time must be finite and non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")
        self._last_monotonic = value
