from __future__ import annotations

import numpy as np

from services.gauge.calibration import NormalizedRect
from services.gauge.privacy import Ws2021PrivacyGuard
from services.vision.realtime_models import RealtimeModelSignals


class Backend:
    def __init__(self, signals: RealtimeModelSignals) -> None:
        self.signals = signals

    def infer(self, image: np.ndarray) -> RealtimeModelSignals:
        return self.signals


def test_privacy_guard_rejects_pose_or_face_overlap() -> None:
    image = np.zeros((300, 500, 3), dtype=np.uint8)
    gauge = NormalizedRect(x=0.4, y=0.3, width=0.2, height=0.4)

    assert Ws2021PrivacyGuard(
        backend=Backend(RealtimeModelSignals(pose_centers=((0.5, 0.5),)))
    ).overlaps(image, gauge)
    assert Ws2021PrivacyGuard(
        backend=Backend(RealtimeModelSignals(face_boxes=((0.45, 0.4, 0.1, 0.1),)))
    ).overlaps(image, gauge)


def test_privacy_guard_allows_distant_person_and_non_skin_gauge() -> None:
    image = np.zeros((300, 500, 3), dtype=np.uint8)
    gauge = NormalizedRect(x=0.7, y=0.3, width=0.2, height=0.4)
    guard = Ws2021PrivacyGuard(
        backend=Backend(
            RealtimeModelSignals(
                pose_centers=((0.1, 0.5),),
                face_boxes=((0.02, 0.1, 0.1, 0.1),),
            )
        )
    )

    assert not guard.overlaps(image, gauge)


def test_privacy_guard_rejects_large_skin_colored_overlap() -> None:
    image = np.zeros((300, 500, 3), dtype=np.uint8)
    image[90:210, 200:300] = (80, 130, 180)
    gauge = NormalizedRect(x=0.4, y=0.3, width=0.2, height=0.4)

    assert Ws2021PrivacyGuard(
        backend=Backend(RealtimeModelSignals())
    ).overlaps(image, gauge)
