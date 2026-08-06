from __future__ import annotations

import base64
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import BinaryIO
from urllib.request import ProxyHandler, Request, build_opener

from packages.contracts.settings import (
    VISUAL_MODEL_NAME,
    VISUAL_OLLAMA_BASE_URL,
)
from packages.contracts.vision import VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame


CHAT_URL = f"{VISUAL_OLLAMA_BASE_URL}/api/chat"
REQUEST_TIMEOUT_SECONDS = 20
MAX_FRAME_BYTES = 1024 * 1024
MAX_REQUEST_IMAGE_BYTES = 4 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
REVIEW_FRAME_COUNT = 4

_SCHEMA_TEXT = json.dumps(
    VisualReview.model_json_schema(),
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
)
REVIEW_PROMPT = (
    "Observe only what is visibly present in these four chronological nursery "
    "bed-zone images. Do not infer identity, sex, emotion, intent, illness, "
    "breathing, suffocation, or a cause. When any field is not clearly visible, "
    "use its uncertain enum instead of guessing. Return only JSON matching this "
    f"schema: {_SCHEMA_TEXT}"
)


class OllamaReviewError(RuntimeError):
    """A stable, redacted local visual-review failure."""


FrameOpener = Callable[[Request, float], AbstractContextManager[BinaryIO]]


def _open_without_proxy(
    request: Request,
    timeout: float,
) -> AbstractContextManager[BinaryIO]:
    opener = build_opener(ProxyHandler({}))
    return opener.open(request, timeout=timeout)  # type: ignore[return-value]


class OllamaVisualReviewer:
    def __init__(
        self,
        *,
        base_url: str = VISUAL_OLLAMA_BASE_URL,
        opener: FrameOpener = _open_without_proxy,
    ) -> None:
        if base_url != VISUAL_OLLAMA_BASE_URL:
            raise ValueError("Ollama origin must use the fixed loopback gateway")
        self._opener = opener

    def review(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> VisualReview:
        try:
            images = self._encode_frames(frames)
            payload = {
                "model": VISUAL_MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": REVIEW_PROMPT,
                        "images": images,
                    }
                ],
                "format": VisualReview.model_json_schema(),
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {"temperature": 0},
            }
            request = Request(
                CHAT_URL,
                data=json.dumps(payload, separators=(",", ":")).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self._opener(request, REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response_too_large")
            return self._parse_response(raw)
        except OllamaReviewError:
            raise
        except Exception:
            raise OllamaReviewError("visual_review_failed") from None

    @staticmethod
    def _encode_frames(
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> list[str]:
        if len(frames) != REVIEW_FRAME_COUNT:
            raise ValueError("invalid_frame_count")
        total = 0
        images: list[str] = []
        for frame in frames:
            if not isinstance(frame.jpeg, bytes) or not 0 < len(frame.jpeg) <= MAX_FRAME_BYTES:
                raise ValueError("invalid_frame_size")
            total += len(frame.jpeg)
            if total > MAX_REQUEST_IMAGE_BYTES:
                raise ValueError("request_images_too_large")
            images.append(base64.b64encode(frame.jpeg).decode("ascii"))
        return images

    @staticmethod
    def _parse_response(raw: bytes) -> VisualReview:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid_response")
        if payload.get("model") != VISUAL_MODEL_NAME or payload.get("done") is not True:
            raise ValueError("invalid_response")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError("invalid_response")
        if (
            message.get("role") != "assistant"
            or not isinstance(message.get("content"), str)
            or "tool_calls" in message
        ):
            raise ValueError("invalid_response")
        return VisualReview.model_validate_json(message["content"])
