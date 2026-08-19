from __future__ import annotations

import cv2
import numpy as np

from packages.monitoring.ws2021_dataset import CandidatePrivacyGuard, PrivacyCandidates
from services.gauge.calibration import NormalizedRect
from services.vision.realtime_models import RealtimeModelBackend


class Ws2021PrivacyGuard:
    def __init__(self, *, backend: RealtimeModelBackend) -> None:
        self._backend = backend

    def overlaps(self, image: np.ndarray, box: NormalizedRect) -> bool:
        signals = self._backend.infer(image)
        persons = tuple(self._pose_box(x, y) for x, y in signals.pose_centers)
        faces = tuple(
            NormalizedRect(x=x, y=y, width=width, height=height)
            for x, y, width, height in signals.face_boxes
            if width > 0 and height > 0 and x + width <= 1 and y + height <= 1
        )

        class FixedBackend:
            def detect(self, frame: np.ndarray) -> PrivacyCandidates:
                return PrivacyCandidates(person_boxes=persons, skin_boxes=faces)

        if CandidatePrivacyGuard(backend=FixedBackend()).overlaps(image, box):
            return True
        height, width = image.shape[:2]
        left = round(box.x * width)
        top = round(box.y * height)
        right = round((box.x + box.width) * width)
        bottom = round((box.y + box.height) * height)
        crop = image[top:bottom, left:right]
        if crop.size == 0:
            return True
        ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
        skin = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
        return float(np.count_nonzero(skin)) / skin.size >= 0.18

    @staticmethod
    def _pose_box(x: float, y: float) -> NormalizedRect:
        left = max(0.0, x - 0.25)
        top = max(0.0, y - 0.45)
        right = min(1.0, x + 0.25)
        bottom = min(1.0, y + 0.45)
        return NormalizedRect(
            x=left,
            y=top,
            width=right - left,
            height=bottom - top,
        )
