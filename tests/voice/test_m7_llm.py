from __future__ import annotations

import json
from contextlib import AbstractContextManager
from io import BytesIO
from typing import BinaryIO

import pytest

from services.voice.m7_llm import (
    LANGUAGE_MODEL_NAME,
    LanguageCandidate,
    LlmUnavailable,
    OllamaLanguageClient,
)


class FakeResponse(BytesIO, AbstractContextManager[BinaryIO]):
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


def response_payload(content: object, *, model: str = LANGUAGE_MODEL_NAME) -> bytes:
    return json.dumps(
        {
            "model": model,
            "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False)},
            "done": True,
        },
        ensure_ascii=False,
    ).encode()


def valid_candidate() -> dict[str, object]:
    return {
        "intent": "feeding_update",
        "tool_calls": [
            {
                "name": "add_feeding_component",
                "arguments": {
                    "kind": "bottle",
                    "liquid_type": "expressed_breast_milk",
                    "amount_ml": 60,
                },
            }
        ],
        "clarification": None,
        "confidence": 0.94,
        "context_key": "conversation-1",
    }


def test_language_client_posts_bounded_text_only_request() -> None:
    assert LANGUAGE_MODEL_NAME == "qwen2.5-coder:7b-instruct"
    opener = RecordingOpener(response_payload(valid_candidate()))
    client = OllamaLanguageClient(opener=opener)

    result = client.complete("宝宝喝了六十毫升母乳", {"phase": "pending"})

    assert isinstance(result, LanguageCandidate)
    assert result.tool_calls[0].name == "add_feeding_component"
    request, timeout = opener.calls[0]
    assert request.full_url == "http://127.0.0.1:11435/api/chat"
    assert timeout == 12
    payload = json.loads(request.data)
    assert payload["model"] == LANGUAGE_MODEL_NAME
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"] == {"temperature": 0}
    assert "images" not in payload["messages"][0]
    assert payload["messages"][0]["content"]
    prompt = payload["messages"][0]["content"]
    assert "add_feeding_component" in prompt
    assert "record_milk_volume" in prompt


def test_language_client_accepts_explicit_candidate_model_for_isolated_evaluation() -> None:
    opener = RecordingOpener(response_payload(valid_candidate(), model="candidate-model"))
    client = OllamaLanguageClient(model_name="candidate-model", opener=opener)

    result = client.complete("宝宝喝了六十毫升母乳", {})

    assert isinstance(result, LanguageCandidate)
    payload = json.loads(opener.calls[0][0].data)
    assert payload["model"] == "candidate-model"


def test_language_client_supports_raw_json_comparison_mode() -> None:
    opener = RecordingOpener(response_payload(valid_candidate()))
    result = OllamaLanguageClient(response_format="json", prompt_variant="current", opener=opener).complete("test", {})

    assert isinstance(result, LanguageCandidate)
    payload = json.loads(opener.calls[0][0].data)
    assert payload["format"] == "json"
    assert payload["messages"][0]["content"].startswith("Return JSON")


def test_language_client_format_repair_only_removes_json_fence() -> None:
    raw = response_payload("```json\n" + json.dumps(valid_candidate()) + "\n```")
    result = OllamaLanguageClient(format_repair=True, opener=RecordingOpener(raw)).complete("test", {})

    assert isinstance(result, LanguageCandidate)


@pytest.mark.parametrize(
    "candidate",
    [
        {**valid_candidate(), "unexpected": True},
        {**valid_candidate(), "tool_calls": [{"name": "drop_database", "arguments": {}}]},
    ],
)
def test_language_client_rejects_unknown_candidate_shape(candidate: dict[str, object]) -> None:
    client = OllamaLanguageClient(opener=RecordingOpener(response_payload(candidate)))

    assert isinstance(client.complete("test", {}), LlmUnavailable)


def test_language_client_rejects_duplicate_json_keys() -> None:
    content = '{"intent":"feeding_update","intent":"start_feeding","tool_calls":[],"clarification":null,"confidence":0.5,"context_key":"c"}'
    client = OllamaLanguageClient(
        opener=RecordingOpener(response_payload(content))
    )

    assert isinstance(client.complete("test", {}), LlmUnavailable)


def test_language_client_maps_transport_failure_to_closed_result() -> None:
    client = OllamaLanguageClient(opener=RecordingOpener(TimeoutError()))

    result = client.complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == "timeout"


def test_language_client_classifies_schema_mismatch_separately() -> None:
    client = OllamaLanguageClient(
        opener=RecordingOpener(response_payload({**valid_candidate(), "unexpected": True}))
    )

    result = client.complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == "schema_mismatch"


def test_language_client_classifies_malformed_json_without_calling_it_a_candidate() -> None:
    raw = json.dumps(
        {
            "model": LANGUAGE_MODEL_NAME,
            "message": {"role": "assistant", "content": "{"},
            "done": True,
        }
    ).encode()
    result = OllamaLanguageClient(opener=RecordingOpener(raw)).complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == "invalid_json"


def test_language_client_classifies_envelope_schema_failures() -> None:
    raw = json.dumps({"model": LANGUAGE_MODEL_NAME, "done": True}).encode()
    result = OllamaLanguageClient(opener=RecordingOpener(raw)).complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == "invalid_response"


def test_language_client_classifies_unknown_tool_separately() -> None:
    payload = response_payload(
        {**valid_candidate(), "tool_calls": [{"name": "drop_database", "arguments": {}}]}
    )
    result = OllamaLanguageClient(opener=RecordingOpener(payload)).complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == "unknown_tool"
