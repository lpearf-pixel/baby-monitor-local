from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageStat, UnidentifiedImageError

from services.vision.frame_policy import PreparedAnalysisFrame


FREEZE_SECONDS = 60.0
OFFLINE_SECONDS = 60.0
RECOVERY_SECONDS = 20.0
MIN_USABLE_LUMA = 3.0
MIN_USABLE_LUMA_STDDEV = 1.0


class FrameHealthState(StrEnum):
    HEALTHY = "healthy"
    RECONNECTING = "reconnecting"
    DEGRADED = "degraded"


class FrameHealthCode(StrEnum):
    RECONNECT_REQUIRED = "reconnect_required"
    FRAME_FROZEN = "frame_frozen"
    SOURCE_OFFLINE = "source_offline"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class FrameHealthTransition:
    state: FrameHealthState
    code: FrameHealthCode
    duration_seconds: float


@dataclass(frozen=True)
class _FrameFingerprint:
    digest: str
    difference_hash: int
    mean_luma: float
    luma_stddev: float
    width: int
    height: int

    @property
    def usable_for_freeze(self) -> bool:
        return (
            self.mean_luma >= MIN_USABLE_LUMA
            and self.luma_stddev >= MIN_USABLE_LUMA_STDDEV
        )


class VisualFrameHealthMonitor:
    def __init__(
        self,
        *,
        open_code: FrameHealthCode | None = None,
    ) -> None:
        if open_code not in {
            None,
            FrameHealthCode.SOURCE_OFFLINE,
            FrameHealthCode.FRAME_FROZEN,
        }:
            raise ValueError("open_code must identify an open frame incident")
        self._last_monotonic: float | None = None
        self._last_fingerprint: _FrameFingerprint | None = None
        self._identical_since: float | None = None
        self._reconnect_fingerprint: _FrameFingerprint | None = None
        self._reconnect_duration = 0.0
        self._failure_since: float | None = None
        self._open_code = open_code
        self._recovery_since: float | None = None
        self._recovery_first: _FrameFingerprint | None = None
        self._recovery_changed = False

    @property
    def open_code(self) -> FrameHealthCode | None:
        return self._open_code

    def observe(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        if (
            frame.captured_at.tzinfo is None
            or frame.captured_at.utcoffset() is None
        ):
            raise ValueError("frame captured_at must be timezone-aware")
        fingerprint = self._fingerprint(frame)
        self._advance_monotonic(monotonic_now)
        self._failure_since = None

        if self._open_code is not None:
            return self._observe_recovery(fingerprint, monotonic_now)

        if not fingerprint.usable_for_freeze:
            self._reset_identical_tracking()
            return None

        if self._last_fingerprint != fingerprint:
            self._last_fingerprint = fingerprint
            self._identical_since = monotonic_now
            self._reconnect_fingerprint = None
            self._reconnect_duration = 0.0
            return None

        if self._identical_since is None:
            self._identical_since = monotonic_now
            return None

        duration = monotonic_now - self._identical_since
        if duration < FREEZE_SECONDS or self._reconnect_fingerprint is not None:
            return None

        self._reconnect_fingerprint = fingerprint
        self._reconnect_duration = duration
        return FrameHealthTransition(
            state=FrameHealthState.RECONNECTING,
            code=FrameHealthCode.RECONNECT_REQUIRED,
            duration_seconds=duration,
        )

    def confirm_reconnect(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        if self._reconnect_fingerprint is None:
            raise RuntimeError("reconnect confirmation was not requested")
        if (
            frame.captured_at.tzinfo is None
            or frame.captured_at.utcoffset() is None
        ):
            raise ValueError("frame captured_at must be timezone-aware")
        fingerprint = self._fingerprint(frame)
        self._advance_monotonic(monotonic_now)
        candidate = self._reconnect_fingerprint
        duration = self._reconnect_duration
        self._reconnect_fingerprint = None
        self._reconnect_duration = 0.0
        self._failure_since = None

        if fingerprint.usable_for_freeze and fingerprint == candidate:
            self._open_code = FrameHealthCode.FRAME_FROZEN
            self._reset_recovery()
            return FrameHealthTransition(
                state=FrameHealthState.DEGRADED,
                code=FrameHealthCode.FRAME_FROZEN,
                duration_seconds=duration,
            )

        self._last_fingerprint = (
            fingerprint if fingerprint.usable_for_freeze else None
        )
        self._identical_since = (
            monotonic_now if fingerprint.usable_for_freeze else None
        )
        return None

    def source_failed(
        self,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        self._advance_monotonic(monotonic_now)
        self._reset_recovery()
        if self._failure_since is None:
            self._failure_since = monotonic_now
            return None
        if self._open_code is not None:
            return None

        duration = monotonic_now - self._failure_since
        if duration < OFFLINE_SECONDS:
            return None

        self._open_code = FrameHealthCode.SOURCE_OFFLINE
        self._reconnect_fingerprint = None
        self._reconnect_duration = 0.0
        return FrameHealthTransition(
            state=FrameHealthState.DEGRADED,
            code=FrameHealthCode.SOURCE_OFFLINE,
            duration_seconds=duration,
        )

    def _observe_recovery(
        self,
        fingerprint: _FrameFingerprint,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        if not fingerprint.usable_for_freeze:
            self._reset_recovery()
            return None
        if self._recovery_since is None:
            self._recovery_since = monotonic_now
            self._recovery_first = fingerprint
            self._recovery_changed = False
            return None
        if fingerprint != self._recovery_first:
            self._recovery_changed = True

        duration = monotonic_now - self._recovery_since
        if duration < RECOVERY_SECONDS or not self._recovery_changed:
            return None

        self._open_code = None
        self._reset_recovery()
        self._last_fingerprint = fingerprint
        self._identical_since = monotonic_now
        return FrameHealthTransition(
            state=FrameHealthState.HEALTHY,
            code=FrameHealthCode.RECOVERED,
            duration_seconds=duration,
        )

    def _advance_monotonic(self, value: float) -> None:
        if value < 0:
            raise ValueError("monotonic time must be non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")
        self._last_monotonic = value

    def _reset_identical_tracking(self) -> None:
        self._last_fingerprint = None
        self._identical_since = None
        self._reconnect_fingerprint = None
        self._reconnect_duration = 0.0

    def _reset_recovery(self) -> None:
        self._recovery_since = None
        self._recovery_first = None
        self._recovery_changed = False

    @staticmethod
    def _fingerprint(frame: PreparedAnalysisFrame) -> _FrameFingerprint:
        try:
            with Image.open(BytesIO(frame.jpeg)) as source:
                if source.format != "JPEG" or source.size != (
                    frame.width,
                    frame.height,
                ):
                    raise ValueError("prepared frame is invalid")
                grayscale = source.convert("L")
                statistics = ImageStat.Stat(grayscale)
                reduced = grayscale.resize((9, 8), Image.Resampling.BILINEAR)
                pixels = list(reduced.get_flattened_data())
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("prepared frame is invalid") from exc

        difference_hash = 0
        for row in range(8):
            for column in range(8):
                left = pixels[row * 9 + column]
                right = pixels[row * 9 + column + 1]
                difference_hash = (difference_hash << 1) | int(left > right)

        return _FrameFingerprint(
            digest=sha256(frame.jpeg).hexdigest(),
            difference_hash=difference_hash,
            mean_luma=round(float(statistics.mean[0]), 3),
            luma_stddev=round(float(statistics.stddev[0]), 3),
            width=frame.width,
            height=frame.height,
        )
