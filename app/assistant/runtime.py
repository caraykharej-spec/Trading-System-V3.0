from __future__ import annotations

import os
from dataclasses import dataclass
from time import monotonic

from app.assistant.model import GroundedLanguageModel, ModelPrompt, ModelReply
from app.assistant.observability import AssistantModelEvent, AssistantTelemetry
from app.assistant.providers.openai_responses import OpenAIResponsesModel
from app.data.reliability import CircuitBreaker, call_with_retry


DEFAULT_OPENAI_MODEL_ALLOWLIST = (
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
)
PROMPT_VERSION = "phase42-grounded-v1"


@dataclass(frozen=True)
class AssistantRuntimeConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-5.6-luna"
    allowed_models: tuple[str, ...] = DEFAULT_OPENAI_MODEL_ALLOWLIST
    timeout_seconds: float = 15.0
    max_output_tokens: int = 700
    max_prompt_chars: int = 24_000
    retry_attempts: int = 1
    retry_backoff_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.provider != "openai":
            raise ValueError("unsupported assistant LLM provider")
        if not self.model:
            raise ValueError("assistant model must not be empty")
        if self.model not in self.allowed_models:
            raise ValueError("assistant model is not in the configured allowlist")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_output_tokens < 1 or self.max_prompt_chars < 1:
            raise ValueError("assistant model budgets must be positive")
        if self.retry_attempts < 1 or self.retry_backoff_seconds < 0:
            raise ValueError("invalid assistant retry configuration")
        if self.circuit_failure_threshold < 1 or self.circuit_recovery_seconds < 0:
            raise ValueError("invalid assistant circuit breaker configuration")

    @classmethod
    def from_env(cls) -> AssistantRuntimeConfig:
        enabled = os.environ.get("TRADING_ASSISTANT_LLM_ENABLED", "0").strip() == "1"
        raw_allowlist = os.environ.get("TRADING_ASSISTANT_LLM_ALLOWED_MODELS", "")
        allowed = tuple(
            item.strip() for item in raw_allowlist.split(",") if item.strip()
        ) or DEFAULT_OPENAI_MODEL_ALLOWLIST
        return cls(
            enabled=enabled,
            provider=os.environ.get("TRADING_ASSISTANT_LLM_PROVIDER", "openai").strip().lower(),
            model=os.environ.get("TRADING_ASSISTANT_LLM_MODEL", "gpt-5.6-luna").strip(),
            allowed_models=allowed,
            timeout_seconds=float(os.environ.get("TRADING_ASSISTANT_LLM_TIMEOUT_SECONDS", "15")),
            max_output_tokens=int(os.environ.get("TRADING_ASSISTANT_LLM_MAX_OUTPUT_TOKENS", "700")),
            max_prompt_chars=int(os.environ.get("TRADING_ASSISTANT_LLM_MAX_PROMPT_CHARS", "24000")),
            retry_attempts=int(os.environ.get("TRADING_ASSISTANT_LLM_RETRY_ATTEMPTS", "1")),
            retry_backoff_seconds=float(
                os.environ.get("TRADING_ASSISTANT_LLM_RETRY_BACKOFF_SECONDS", "0.25")
            ),
            circuit_failure_threshold=int(
                os.environ.get("TRADING_ASSISTANT_LLM_CIRCUIT_FAILURE_THRESHOLD", "3")
            ),
            circuit_recovery_seconds=float(
                os.environ.get("TRADING_ASSISTANT_LLM_CIRCUIT_RECOVERY_SECONDS", "60")
            ),
        )


class ProductionLanguageModel:
    """Reliability and telemetry boundary around a grounded language model."""

    def __init__(
        self,
        inner: GroundedLanguageModel,
        *,
        provider: str,
        model: str,
        telemetry: AssistantTelemetry,
        retry_attempts: int = 1,
        retry_backoff_seconds: float = 0.25,
        circuit_failure_threshold: int = 3,
        circuit_recovery_seconds: float = 60.0,
    ) -> None:
        self._inner = inner
        self._provider = provider
        self._model = model
        self._telemetry = telemetry
        self._retry_attempts = retry_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._circuit = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_seconds=circuit_recovery_seconds,
        )

    @property
    def circuit_open(self) -> bool:
        return self._circuit.is_open

    def generate(self, prompt: ModelPrompt) -> ModelReply:
        started = monotonic()
        try:
            self._circuit.before_call()
            reply = call_with_retry(
                lambda: self._inner.generate(prompt),
                attempts=self._retry_attempts,
                backoff_seconds=self._retry_backoff_seconds,
            )
            self._circuit.record_success()
            self._record(prompt, reply, started, "success", None)
            return reply
        except Exception as exc:
            self._circuit.record_failure()
            self._record(prompt, None, started, "failure", exc.__class__.__name__)
            raise

    def _record(
        self,
        prompt: ModelPrompt,
        reply: ModelReply | None,
        started: float,
        outcome: str,
        error_type: str | None,
    ) -> None:
        self._telemetry.record(
            AssistantModelEvent(
                provider=self._provider,
                model=self._model,
                prompt_version=PROMPT_VERSION,
                outcome=outcome,
                latency_ms=(monotonic() - started) * 1000,
                evidence_count=len(prompt.evidence),
                output_chars=len(reply.text) if reply is not None else 0,
                input_tokens=reply.input_tokens if reply is not None else None,
                output_tokens=reply.output_tokens if reply is not None else None,
                error_type=error_type,
            )
        )


def build_production_language_model(
    config: AssistantRuntimeConfig,
    telemetry: AssistantTelemetry,
) -> GroundedLanguageModel | None:
    """Construct the optional model from environment-backed configuration.

    Disabled configuration is deterministic-only. Enabled configuration fails
    closed when the required secret is absent instead of silently downgrading.
    """

    if not config.enabled:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when assistant LLM is enabled")
    provider = OpenAIResponsesModel(
        api_key=api_key,
        model=config.model,
        allowed_models=config.allowed_models,
        timeout_seconds=config.timeout_seconds,
        max_output_tokens=config.max_output_tokens,
        max_prompt_chars=config.max_prompt_chars,
    )
    return ProductionLanguageModel(
        provider,
        provider=config.provider,
        model=config.model,
        telemetry=telemetry,
        retry_attempts=config.retry_attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
        circuit_failure_threshold=config.circuit_failure_threshold,
        circuit_recovery_seconds=config.circuit_recovery_seconds,
    )
