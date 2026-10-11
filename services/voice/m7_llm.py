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


LANGUAGE_MODEL_NAME = "qwen3:8b-instruct-q4_K_M"
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

_SCHEMA_PROMPT = (
    "Return only JSON with keys intent, tool_calls, clarification, confidence, "
    "context_key. Feeding tools only; never invent identity, permission, saved "
    "state, database results, or millilitres for direct breastfeeding."
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


@dataclass(frozen=True, slots=True)
class LlmUnavailable:
    reason: str = "llm_unavailable"


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
        opener: FrameOpener = _open_without_proxy,
    ) -> None:
        if base_url != VISUAL_OLLAMA_BASE_URL:
            raise ValueError("Ollama origin must use the fixed loopback gateway")
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
                "model": LANGUAGE_MODEL_NAME,
                "messages": [
                    {"role": "system", "content": _SCHEMA_PROMPT},
                    {"role": "user", "content": json.dumps(
                        {"text": text, "context": context},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )},
                ],
                "format": LanguageCandidate.model_json_schema(),
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
            candidate = self._parse_response(raw)
            if any(call.name not in _ALLOWED_TOOLS for call in candidate.tool_calls):
                raise ValueError("unknown_tool")
            return candidate
        except Exception:
            return LlmUnavailable()

    @staticmethod
    def _parse_response(raw: bytes) -> LanguageCandidate:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(payload, dict):
            raise ValueError("invalid_response")
        if payload.get("model") != LANGUAGE_MODEL_NAME or payload.get("done") is not True:
            raise ValueError("invalid_response")
        message = payload.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("invalid_response")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("invalid_response")
        candidate_payload = json.loads(content, object_pairs_hook=_reject_duplicate_keys)
        candidate = LanguageCandidate.model_validate(candidate_payload)
        if candidate.intent == "clarification" and not candidate.clarification:
            raise ValidationError.from_exception_data(
                "LanguageCandidate", [{"type": "value_error", "loc": ("clarification",), "input": None, "ctx": {"error": "required"}}]
            )
        return candidate


__all__ = [
    "LANGUAGE_MODEL_NAME",
    "LanguageCandidate",
    "LlmUnavailable",
    "M7ToolCall",
    "OllamaLanguageClient",
]
