from __future__ import annotations

import base64
import json
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import BinaryIO
from urllib.request import ProxyHandler

import pytest

from services.vision.frame_policy import PreparedAnalysisFrame


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def frame(index: int, *, size: int = 32) -> PreparedAnalysisFrame:
    return PreparedAnalysisFrame(
        jpeg=bytes([index + 1]) * size,
        captured_at=NOW + timedelta(seconds=index * 2),
        width=960,
        height=540,
        crop_box=(0, 0, 960, 540),
    )


def frames(*, size: int = 32) -> tuple[PreparedAnalysisFrame, ...]:
    return tuple(frame(index, size=size) for index in range(4))


def valid_review() -> dict[str, object]:
    return {
        "schema_version": 1,
        "baby_visibility": "visible",
        "face_visibility": "clear",
        "posture": "supine",
        "bed_state": "inside",
        "adult_presence": "absent",
        "image_quality": "usable",
        "risk": "none",
        "reason_codes": [],
        "confidence": 0.91,
    }


def response_payload(**overrides: object) -> bytes:
    payload: dict[str, object] = {
        "model": "qwen3-vl:8b-instruct-q4_K_M",
        "created_at": "2026-08-06T12:00:00Z",
        "message": {
            "role": "assistant",
            "content": json.dumps(valid_review()),
        },
        "done": True,
        "done_reason": "stop",
        "total_duration": 1_000_000,
    }
    payload.update(overrides)
    return json.dumps(payload).encode()


class FakeResponse(BytesIO, AbstractContextManager[BinaryIO]):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class RecordingOpener:
    def __init__(self, payload: bytes | Exception) -> None:
        self.payload = payload
        self.calls: list[tuple[object, float]] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        if isinstance(self.payload, Exception):
            raise self.payload
        return FakeResponse(self.payload)


def client_module():
    from services.vision import ollama_client

    return ollama_client


def test_review_posts_exact_bounded_local_chat_request() -> None:
    module = client_module()
    opener = RecordingOpener(response_payload())
    reviewer = module.OllamaVisualReviewer(opener=opener)

    review = reviewer.review(frames())

    assert review.confidence == 0.91
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == "http://127.0.0.1:11435/api/chat"
    assert request.method == "POST"
    assert timeout == 20
    payload = json.loads(request.data)
    assert payload["model"] == "qwen3-vl:8b-instruct-q4_K_M"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == "5m"
    assert payload["options"] == {"temperature": 0}
    assert payload["format"] == module.VisualReview.model_json_schema()
    assert "tools" not in payload
    messages = payload["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == module.REVIEW_PROMPT
    assert messages[0]["images"] == [
        base64.b64encode(item.jpeg).decode("ascii") for item in frames()
    ]
    serialized = request.data.decode()
    assert "file://" not in serialized
    assert "/private/" not in serialized


def test_default_transport_disables_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    module = client_module()
    captured_handlers: list[object] = []
    opener = RecordingOpener(response_payload())

    class BuiltOpener:
        def open(self, request: object, timeout: float) -> FakeResponse:
            return opener(request, timeout)

    def fake_build_opener(*handlers: object) -> BuiltOpener:
        captured_handlers.extend(handlers)
        return BuiltOpener()

    monkeypatch.setattr(module, "build_opener", fake_build_opener)

    module.OllamaVisualReviewer().review(frames())

    proxy_handlers = [item for item in captured_handlers if isinstance(item, ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


@pytest.mark.parametrize("count", [0, 3, 5])
def test_review_requires_exactly_four_frames(count: int) -> None:
    module = client_module()
    opener = RecordingOpener(response_payload())
    reviewer = module.OllamaVisualReviewer(opener=opener)

    with pytest.raises(module.OllamaReviewError, match="visual_review_failed"):
        reviewer.review(frames()[:count] if count <= 4 else (*frames(), frame(4)))

    assert opener.calls == []


def test_review_rejects_per_frame_and_total_byte_overflow() -> None:
    module = client_module()
    opener = RecordingOpener(response_payload())
    reviewer = module.OllamaVisualReviewer(opener=opener)

    oversized = (frame(0, size=1024 * 1024 + 1), *frames()[1:])
    with pytest.raises(module.OllamaReviewError, match="visual_review_failed"):
        reviewer.review(oversized)

    total_overflow = tuple(frame(index, size=1024 * 1024) for index in range(4))
    total_overflow = (
        *total_overflow[:3],
        frame(3, size=1024 * 1024 + 1),
    )
    with pytest.raises(module.OllamaReviewError, match="visual_review_failed"):
        reviewer.review(total_overflow)
    assert opener.calls == []


@pytest.mark.parametrize(
    "base_url",
    [
        "http://0.0.0.0:11435",
        "http://127.0.0.1:11434",
        "https://models.example.test",
        "http://127.0.0.1:11435/api/generate",
    ],
)
def test_reviewer_rejects_any_alternate_origin_or_path(base_url: str) -> None:
    module = client_module()

    with pytest.raises(ValueError, match="fixed loopback"):
        module.OllamaVisualReviewer(base_url=base_url)


@pytest.mark.parametrize(
    "payload",
    [
        response_payload(model="qwen3-vl:8b"),
        response_payload(done=False),
        response_payload(message={"role": "assistant", "content": "not-json"}),
        response_payload(
            message={
                "role": "assistant",
                "content": json.dumps({**valid_review(), "free_text": "unsafe"}),
            }
        ),
        response_payload(message={"role": "assistant", "content": json.dumps(valid_review()), "tool_calls": []}),
    ],
)
def test_invalid_ollama_or_model_response_fails_closed(payload: bytes) -> None:
    module = client_module()
    reviewer = module.OllamaVisualReviewer(opener=RecordingOpener(payload))

    with pytest.raises(module.OllamaReviewError, match="visual_review_failed"):
        reviewer.review(frames())


def test_oversized_response_and_transport_details_are_redacted() -> None:
    module = client_module()
    oversized = b"{" + b"x" * (module.MAX_RESPONSE_BYTES + 1)
    reviewer = module.OllamaVisualReviewer(opener=RecordingOpener(oversized))
    with pytest.raises(module.OllamaReviewError) as response_failure:
        reviewer.review(frames())
    assert str(response_failure.value) == "visual_review_failed"

    reviewer = module.OllamaVisualReviewer(
        opener=RecordingOpener(OSError("credential at /private/family/model"))
    )
    with pytest.raises(module.OllamaReviewError) as transport_failure:
        reviewer.review(frames())
    assert str(transport_failure.value) == "visual_review_failed"
    assert "/private" not in repr(transport_failure.value)

