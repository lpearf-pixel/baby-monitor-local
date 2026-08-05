from __future__ import annotations

from collections import deque
from datetime import timedelta

from services.vision.frame_policy import PreparedAnalysisFrame


RETENTION_SECONDS = 40
MAX_FRAMES = 21


class AnalysisFrameRing:
    def __init__(self) -> None:
        self._frames: deque[PreparedAnalysisFrame] = deque(maxlen=MAX_FRAMES)

    def __len__(self) -> int:
        return len(self._frames)

    def add(self, frame: PreparedAnalysisFrame) -> None:
        captured_at = frame.captured_at
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("frame captured_at must be timezone-aware")
        if self._frames and captured_at < self._frames[-1].captured_at:
            raise ValueError("frame captured_at must be monotonic")

        self._frames.append(frame)
        cutoff = captured_at - timedelta(seconds=RETENTION_SECONDS)
        while self._frames and self._frames[0].captured_at < cutoff:
            self._frames.popleft()

    def select_review_frames(
        self,
        *,
        count: int = 4,
        spacing_seconds: int = 2,
    ) -> tuple[PreparedAnalysisFrame, ...]:
        if not 1 <= count <= MAX_FRAMES:
            raise ValueError("count must be between 1 and 21")
        if not 1 <= spacing_seconds <= RETENTION_SECONDS:
            raise ValueError("spacing_seconds must be between 1 and 40")
        if len(self._frames) < count:
            return ()

        frames = tuple(self._frames)
        latest = frames[-1].captured_at
        targets = tuple(
            latest - timedelta(seconds=spacing_seconds * offset)
            for offset in reversed(range(count))
        )
        unused = set(range(len(frames)))
        selected_indexes: list[int] = []
        for target in targets:
            index = min(
                unused,
                key=lambda candidate: (
                    abs((frames[candidate].captured_at - target).total_seconds()),
                    frames[candidate].captured_at,
                ),
            )
            distance = abs(
                (frames[index].captured_at - target).total_seconds()
            )
            if distance > spacing_seconds:
                return ()
            unused.remove(index)
            selected_indexes.append(index)

        selected = tuple(frames[index] for index in sorted(selected_indexes))
        if any(
            later.captured_at < earlier.captured_at
            for earlier, later in zip(selected, selected[1:])
        ):
            return ()
        return selected
