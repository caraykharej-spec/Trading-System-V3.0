from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.assistant.model import ModelPrompt, ModelReply


_CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_:\-]+)\]")


class OpenAIResponsesTransport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        api_key: str,
        payload: dict[str, Any],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


def _default_transport(
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Trading-System-V3.0/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("OpenAI Responses request failed") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("OpenAI Responses payload is not an object")
    return decoded


def _extract_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    if not parts:
        raise RuntimeError("OpenAI Responses output contains no text")
    return "\n".join(parts)


def _extract_usage(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    return (
        input_tokens if isinstance(input_tokens, int) else None,
        output_tokens if isinstance(output_tokens, int) else None,
    )


@dataclass(frozen=True)
class OpenAIResponsesModel:
    """Grounded narrator backed by the OpenAI Responses API.

    The adapter receives only the bounded Phase 41 prompt contract. It has no
    tools, no execution callback, and no access to live-operation interfaces.
    """

    api_key: str
    model: str
    allowed_models: tuple[str, ...]
    timeout_seconds: float = 15.0
    max_output_tokens: int = 700
    max_prompt_chars: int = 24_000
    endpoint: str = "https://api.openai.com/v1/responses"
    transport: OpenAIResponsesTransport = _default_transport
    provider_name: str = "openai"

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenAI API key must not be empty")
        if not self.model.strip():
            raise ValueError("OpenAI model must not be empty")
        if self.model not in self.allowed_models:
            raise ValueError("OpenAI model is not in the configured allowlist")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if self.max_prompt_chars < 1:
            raise ValueError("max_prompt_chars must be positive")

    def generate(self, prompt: ModelPrompt) -> ModelReply:
        evidence_lines = [
            (
                f"[{item.citation_id}] symbol={item.symbol or 'MARKET'} "
                f"source={item.source} key={item.key} value={item.value}"
            )
            for item in prompt.evidence
        ]
        history = "\n".join(f"- {item}" for item in prompt.history[-6:]) or "- none"
        user_input = (
            f"Intent: {prompt.intent.value}\n"
            f"Symbol: {prompt.symbol or 'NONE'}\n"
            f"Recent user queries:\n{history}\n\n"
            f"Grounded evidence:\n" + "\n".join(evidence_lines) + "\n\n"
            f"Current question: {prompt.query}\n\n"
            "Answer using only grounded evidence. Include every citation ID you rely on "
            "visibly in square brackets. If evidence is insufficient, say UNKNOWN."
        )
        if len(user_input) > self.max_prompt_chars:
            raise ValueError("grounded model prompt exceeds configured character budget")

        payload = self.transport(
            url=self.endpoint,
            api_key=self.api_key,
            payload={
                "model": self.model,
                "instructions": prompt.system_instructions,
                "input": user_input,
                "max_output_tokens": self.max_output_tokens,
            },
            timeout_seconds=self.timeout_seconds,
        )
        text = _extract_text(payload)
        citations = tuple(dict.fromkeys(_CITATION_PATTERN.findall(text)))
        input_tokens, output_tokens = _extract_usage(payload)
        return ModelReply(
            text=text,
            citations=citations,
            provider=self.provider_name,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
