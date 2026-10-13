"""Bounded local Ollama language transport for the M7 feeding assistant."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import BinaryIO, Literal
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.contracts.settings import VISUAL_OLLAMA_BASE_URL


LANGUAGE_MODEL_NAME = "qwen2.5-coder:7b-instruct"
CHAT_URL = f"{VISUAL_OLLAMA_BASE_URL}/api/chat"
REQUEST_TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 64 * 1024
MAX_INPUT_TEXT_BYTES = 8 * 1024
MAX_CONTEXT_BYTES = 8 * 1024
MAX_TOOL_CALLS = 8
_ALLOWED_TOOLS = {
    "get_active_feeding",
    "start_feeding",
    "add_feeding_component",
    "correct_feeding_component",
    "end_feeding",
    "request_feeding_confirmation",
    "confirm_feeding",
    "cancel_feeding",
    "get_recent_feedings",
    "get_feeding_summary",
}


class _InvalidResponse(ValueError):
    """The Ollama envelope is not a valid bounded chat response."""


class _UnknownTool(ValueError):
    """The model selected a tool outside the closed M7 registry."""

_SCHEMA_PROMPT = (
    "Return only JSON with keys intent, tool_calls, clarification, confidence, context_key. "
    "Use only these exact tool names: get_active_feeding, start_feeding, "
    "add_feeding_component, correct_feeding_component, end_feeding, "
    "request_feeding_confirmation, confirm_feeding, cancel_feeding, "
    "get_recent_feedings, get_feeding_summary. Never invent another name such as "
    "record_milk_volume or feed_baby. For add_feeding_component use exactly one of: "
    "{kind:bottle,liquid_type:expressed_breast_milk,amount_ml:integer} or "
    "{kind:bottle,liquid_type:formula,amount_ml:integer} or "
    "{kind:direct_breastfeeding,duration_minutes:integer}. For corrections use "
    "{target:formula|expressed_breast_milk,amount_ml:integer}. Other tool arguments "
    "are {}. Feeding tools only; never invent identity, permission, saved state, "
    "database results, or millilitres for direct breastfeeding."
)
_BASE_PROMPT = "Return JSON with intent, tool_calls, clarification, confidence, context_key."
_MINIMAL_SCHEMA_PROMPT = (
    "Return only the minimal semantic JSON fields: intent, action, milk_type, "
    "explicit_amount_ml, duration_minutes, correction_target, needs_clarification. "
    "Use null for unknown optional values. Never output IDs, signatures, versions, "
    "confirmation tokens, database fields, tool names, or saved state."
)


class M7ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object]


class LanguageCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal[
        "feeding_start",
        "feeding_update",
        "feeding_end",
        "care_confirm",
        "care_cancel",
        "feeding_query",
        "feeding_resume",
        "clarification",
    ]
    tool_calls: list[M7ToolCall] = Field(max_length=MAX_TOOL_CALLS)
    clarification: str | None = Field(default=None, max_length=256)
    confidence: float = Field(ge=0.0, le=1.0)
    context_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MinimalSemanticCandidate(BaseModel):
    """Experimental model-facing semantics; no authority or persistence fields."""

    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Literal[
        "feeding_start",
        "feeding_update",
        "feeding_end",
        "care_confirm",
        "care_cancel",
        "feeding_query",
        "feeding_resume",
        "clarification",
    ]
    action: Literal[
        "start",
        "add_component",
        "end",
        "confirm",
        "cancel",
        "query",
        "resume",
        "clarify",
    ]
    milk_type: Literal["expressed_breast_milk", "formula"] | None = None
    explicit_amount_ml: int | None = Field(default=None, ge=1, le=2000)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    correction_target: Literal["expressed_breast_milk", "formula"] | None = None
    needs_clarification: bool


def semantic_candidate_to_language_candidate(
    candidate: MinimalSemanticCandidate,
) -> LanguageCandidate:
    """Adapt bounded model semantics into the existing closed tool candidate."""
    context_key = "m7-minimal-experiment"
    if candidate.needs_clarification or candidate.action == "clarify":
        return LanguageCandidate(
            intent="clarification",
            tool_calls=[],
            clarification="请说明奶种和明确数量，或说明亲喂时长。",
            confidence=0.0,
            context_key=context_key,
        )
    if candidate.action == "start":
        return LanguageCandidate(intent="feeding_start", tool_calls=[M7ToolCall(name="start_feeding", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "end":
        return LanguageCandidate(intent="feeding_end", tool_calls=[M7ToolCall(name="end_feeding", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "confirm":
        return LanguageCandidate(intent="care_confirm", tool_calls=[M7ToolCall(name="confirm_feeding", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "cancel":
        return LanguageCandidate(intent="care_cancel", tool_calls=[M7ToolCall(name="cancel_feeding", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "query":
        return LanguageCandidate(intent="feeding_query", tool_calls=[M7ToolCall(name="get_recent_feedings", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "resume":
        return LanguageCandidate(intent="feeding_resume", tool_calls=[M7ToolCall(name="get_active_feeding", arguments={})], confidence=0.0, context_key=context_key)
    if candidate.action == "add_component":
        if candidate.correction_target is not None and candidate.explicit_amount_ml is not None:
            return LanguageCandidate(intent="feeding_update", tool_calls=[M7ToolCall(name="correct_feeding_component", arguments={"target": candidate.correction_target, "amount_ml": candidate.explicit_amount_ml})], confidence=0.0, context_key=context_key)
        if candidate.milk_type == "expressed_breast_milk" and candidate.explicit_amount_ml is not None:
            args = {"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": candidate.explicit_amount_ml}
        elif candidate.milk_type == "formula" and candidate.explicit_amount_ml is not None:
            args = {"kind": "bottle", "liquid_type": "formula", "amount_ml": candidate.explicit_amount_ml}
        elif candidate.duration_minutes is not None and candidate.milk_type is None and candidate.explicit_amount_ml is None:
            args = {"kind": "direct_breastfeeding", "duration_minutes": candidate.duration_minutes}
        else:
            return LanguageCandidate(intent="clarification", tool_calls=[], clarification="请说明奶种和明确数量，或说明亲喂时长。", confidence=0.0, context_key=context_key)
        return LanguageCandidate(intent="feeding_update", tool_calls=[M7ToolCall(name="add_feeding_component", arguments=args)], confidence=0.0, context_key=context_key)
    return LanguageCandidate(intent="clarification", tool_calls=[], clarification="请重新说明护理操作。", confidence=0.0, context_key=context_key)


@dataclass(frozen=True, slots=True)
class LlmUnavailable:
    reason: str = "llm_unavailable"


def _schema_failure_reason(error: ValidationError) -> str:
    """Map model-shape failures to bounded diagnostic categories only."""
    error_types = {str(item.get("type", "")) for item in error.errors()}
    if "missing" in error_types:
        return "schema_missing_field"
    if "extra_forbidden" in error_types:
        return "schema_extra_field"
    if "literal_error" in error_types:
        return "schema_enum_mismatch"
    if any(
        item.endswith(("_type", "_parsing", "_from_union"))
        for item in error_types
    ):
        return "schema_type_mismatch"
    return "schema_mismatch"


FrameOpener = Callable[[Request, float], AbstractContextManager[BinaryIO]]


def _open_without_proxy(
    request: Request,
    timeout: float,
) -> AbstractContextManager[BinaryIO]:
    opener = build_opener(ProxyHandler({}))
    return opener.open(request, timeout=timeout)  # type: ignore[return-value]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


class OllamaLanguageClient:
    def __init__(
        self,
        *,
        base_url: str = VISUAL_OLLAMA_BASE_URL,
        model_name: str = LANGUAGE_MODEL_NAME,
        response_format: Literal["json", "schema"] = "schema",
        prompt_variant: Literal["current", "optimized"] = "optimized",
        format_repair: bool = False,
        schema_profile: Literal["full", "minimal"] = "full",
        opener: FrameOpener = _open_without_proxy,
    ) -> None:
        if base_url != VISUAL_OLLAMA_BASE_URL:
            raise ValueError("Ollama origin must use the fixed loopback gateway")
        if not isinstance(model_name, str) or not model_name or len(model_name) > 128:
            raise ValueError("invalid model name")
        if response_format not in {"json", "schema"}:
            raise ValueError("invalid response format")
        if schema_profile not in {"full", "minimal"}:
            raise ValueError("invalid schema profile")
        self._model_name = model_name
        self._response_format = response_format
        self._prompt_variant = prompt_variant
        self._format_repair = format_repair
        self._schema_profile = schema_profile
        self._opener = opener

    def complete(
        self,
        text: str,
        context: dict[str, object],
    ) -> LanguageCandidate | LlmUnavailable:
        try:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty_text")
            text_bytes = text.encode("utf-8")
            context_bytes = json.dumps(
                context, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            if len(text_bytes) > MAX_INPUT_TEXT_BYTES or len(context_bytes) > MAX_CONTEXT_BYTES:
                raise ValueError("input_too_large")
            payload = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": _MINIMAL_SCHEMA_PROMPT if self._schema_profile == "minimal" else (_SCHEMA_PROMPT if self._prompt_variant == "optimized" else _BASE_PROMPT)},
                    {"role": "user", "content": json.dumps(
                        {"text": text, "context": context},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )},
                ],
                "format": MinimalSemanticCandidate.model_json_schema()
                if self._schema_profile == "minimal" and self._response_format == "schema"
                else LanguageCandidate.model_json_schema()
                if self._response_format == "schema"
                else "json",
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {"temperature": 0},
            }
            request = Request(
                CHAT_URL,
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self._opener(request, REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response_too_large")
            candidate = self._parse_response(
                raw,
                model_name=self._model_name,
                format_repair=self._format_repair,
                schema_profile=self._schema_profile,
            )
            if any(call.name not in _ALLOWED_TOOLS for call in candidate.tool_calls):
                raise _UnknownTool("unknown_tool")
            return candidate
        except TimeoutError:
            return LlmUnavailable("timeout")
        except (OSError, ConnectionError):
            return LlmUnavailable("transport_failure")
        except json.JSONDecodeError:
            return LlmUnavailable("invalid_json")
        except _UnknownTool:
            return LlmUnavailable("unknown_tool")
        except _InvalidResponse:
            return LlmUnavailable("invalid_response")
        except ValidationError as exc:
            return LlmUnavailable(_schema_failure_reason(exc))
        except ValueError:
            return LlmUnavailable("invalid_candidate")
        except Exception:
            return LlmUnavailable()

    @staticmethod
    def _parse_response(
        raw: bytes,
        *,
        model_name: str = LANGUAGE_MODEL_NAME,
        format_repair: bool = False,
        schema_profile: Literal["full", "minimal"] = "full",
    ) -> LanguageCandidate:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise _InvalidResponse("invalid_response")
        if payload.get("model") != model_name or payload.get("done") is not True:
            raise _InvalidResponse("invalid_response")
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise _InvalidResponse("invalid_response")
        content = message.get("content")
        if not isinstance(content, str):
            raise _InvalidResponse("invalid_response")
        candidate_payload = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
        if format_repair and isinstance(candidate_payload, str):
            fenced = candidate_payload.strip()
            if fenced.startswith("```") and fenced.endswith("```"):
                fenced = fenced[fenced.find("\n") + 1 : -3].strip()
                candidate_payload = json.loads(fenced, object_pairs_hook=_reject_duplicate_keys)
        if schema_profile == "minimal":
            return semantic_candidate_to_language_candidate(
                MinimalSemanticCandidate.model_validate(candidate_payload)
            )
        candidate = LanguageCandidate.model_validate(candidate_payload)
        if candidate.intent == "clarification" and not candidate.clarification:
            raise ValidationError.from_exception_data(
                "LanguageCandidate", [{"type": "value_error", "loc": ("clarification",), "input": None, "ctx": {"error": "required"}}]
            )
        return candidate


__all__ = [
    "LANGUAGE_MODEL_NAME",
    "LanguageCandidate",
    "MinimalSemanticCandidate",
    "LlmUnavailable",
    "M7ToolCall",
    "OllamaLanguageClient",
    "semantic_candidate_to_language_candidate",
]
