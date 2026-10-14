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
    MinimalSemanticCandidate,
    MinimalSemanticV2Candidate,
    semantic_candidate_to_language_candidate,
    semantic_candidate_v2_to_language_candidate,
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


def test_minimal_semantic_candidate_contains_no_authority_fields() -> None:
    candidate = MinimalSemanticCandidate(
        intent="feeding_update",
        action="add_component",
        milk_type="formula",
        explicit_amount_ml=30,
        duration_minutes=None,
        correction_target=None,
        needs_clarification=False,
    )

    adapted = semantic_candidate_to_language_candidate(candidate)

    assert adapted.tool_calls[0].name == "add_feeding_component"
    assert adapted.tool_calls[0].arguments == {
        "kind": "bottle",
        "liquid_type": "formula",
        "amount_ml": 30,
    }
    assert "request_id" not in candidate.model_dump()
    assert "signature" not in candidate.model_dump()


def test_minimal_semantic_candidate_requires_clarification_without_milk_type() -> None:
    candidate = MinimalSemanticCandidate(
        intent="feeding_update",
        action="add_component",
        milk_type=None,
        explicit_amount_ml=30,
        duration_minutes=None,
        correction_target=None,
        needs_clarification=True,
    )

    adapted = semantic_candidate_to_language_candidate(candidate)

    assert adapted.intent == "clarification"
    assert adapted.tool_calls == []
    assert adapted.clarification


def test_language_client_minimal_profile_uses_minimal_schema_and_adapts() -> None:
    payload = {
        "intent": "feeding_update",
        "action": "add_component",
        "milk_type": "formula",
        "explicit_amount_ml": 30,
        "duration_minutes": None,
        "correction_target": None,
        "needs_clarification": False,
    }
    opener = RecordingOpener(response_payload(payload))
    result = OllamaLanguageClient(schema_profile="minimal", opener=opener).complete("test", {})

    assert isinstance(result, LanguageCandidate)
    assert result.tool_calls[0].name == "add_feeding_component"
    request_payload = json.loads(opener.calls[0][0].data)
    assert "tool_calls" not in request_payload["format"]["properties"]
    assert "request_id" not in request_payload["format"]["properties"]


@pytest.mark.parametrize(
    ("candidate", "tool", "arguments"),
    [
        (
            {"intent": "feeding_update", "action": "add_component", "milk_type": "expressed_breast_milk", "explicit_amount_ml": 60, "duration_minutes": None, "correction_target": None, "needs_clarification": False},
            "add_feeding_component",
            {"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60},
        ),
        (
            {"intent": "feeding_update", "action": "add_component", "milk_type": None, "explicit_amount_ml": None, "duration_minutes": 15, "correction_target": None, "needs_clarification": False},
            "add_feeding_component",
            {"kind": "direct_breastfeeding", "duration_minutes": 15},
        ),
        (
            {"intent": "feeding_update", "action": "add_component", "milk_type": None, "explicit_amount_ml": 40, "duration_minutes": None, "correction_target": "formula", "needs_clarification": False},
            "correct_feeding_component",
            {"target": "formula", "amount_ml": 40},
        ),
    ],
)
def test_minimal_adapter_preserves_component_semantics(candidate: dict[str, object], tool: str, arguments: dict[str, object]) -> None:
    adapted = semantic_candidate_to_language_candidate(MinimalSemanticCandidate.model_validate(candidate))

    assert adapted.tool_calls[0].name == tool
    assert adapted.tool_calls[0].arguments == arguments


def test_minimal_v2_preserves_two_bottle_components() -> None:
    candidate = MinimalSemanticV2Candidate(
        intent="feeding_update",
        action="add_components",
        components=[
            {"kind": "bottle", "milk_type": "expressed_breast_milk", "amount_ml": 60, "duration_minutes": None},
            {"kind": "bottle", "milk_type": "formula", "amount_ml": 30, "duration_minutes": None},
        ],
        correction_target=None,
        needs_clarification=False,
    )

    adapted = semantic_candidate_v2_to_language_candidate(candidate)

    assert [call.arguments for call in adapted.tool_calls] == [
        {"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60},
        {"kind": "bottle", "liquid_type": "formula", "amount_ml": 30},
    ]


def test_minimal_v2_rejects_duplicate_milk_components_by_clarifying() -> None:
    candidate = MinimalSemanticV2Candidate(
        intent="feeding_update",
        action="add_components",
        components=[
            {"kind": "bottle", "milk_type": "formula", "amount_ml": 30, "duration_minutes": None},
            {"kind": "bottle", "milk_type": "formula", "amount_ml": 40, "duration_minutes": None},
        ],
        correction_target=None,
        needs_clarification=False,
    )

    adapted = semantic_candidate_v2_to_language_candidate(candidate)

    assert adapted.intent == "clarification"
    assert adapted.tool_calls == []


def test_language_client_minimal_v2_profile_preserves_components() -> None:
    payload = {
        "intent": "feeding_update",
        "action": "add_components",
        "components": [
            {"kind": "bottle", "milk_type": "expressed_breast_milk", "amount_ml": 60, "duration_minutes": None},
            {"kind": "bottle", "milk_type": "formula", "amount_ml": 30, "duration_minutes": None},
        ],
        "correction_target": None,
        "needs_clarification": False,
    }
    opener = RecordingOpener(response_payload(payload))
    result = OllamaLanguageClient(schema_profile="minimal_v2", opener=opener).complete("test", {})

    assert isinstance(result, LanguageCandidate)
    assert len(result.tool_calls) == 2
    schema = json.loads(opener.calls[0][0].data)["format"]
    assert "components" in schema["properties"]


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


def test_language_client_semantic_focus_prompt_is_opt_in_and_keeps_closed_tools() -> None:
    opener = RecordingOpener(response_payload(valid_candidate()))
    result = OllamaLanguageClient(
        prompt_variant="semantic_focus", opener=opener
    ).complete("宝宝喝了六十毫升母乳", {})

    assert isinstance(result, LanguageCandidate)
    prompt = json.loads(opener.calls[0][0].data)["messages"][0]["content"]
    assert "feeding_update" in prompt
    assert "feeding_query" in prompt
    assert "Never guess a milk amount" in prompt
    assert "add_feeding_component" in prompt


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
    assert result.reason == "schema_extra_field"


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        ({key: value for key, value in valid_candidate().items() if key != "intent"}, "schema_missing_field"),
        ({**valid_candidate(), "intent": "not_an_intent"}, "schema_enum_mismatch"),
        ({**valid_candidate(), "confidence": "high"}, "schema_type_mismatch"),
    ],
)
def test_language_client_classifies_schema_field_failures(
    candidate: dict[str, object], reason: str
) -> None:
    result = OllamaLanguageClient(opener=RecordingOpener(response_payload(candidate))).complete("test", {})

    assert isinstance(result, LlmUnavailable)
    assert result.reason == reason


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
