from __future__ import annotations

from typing import Any

import pytest

from app.assistant.model import ModelPrompt, ModelReply
from app.assistant.models import AssistantIntent, EvidenceCitation
from app.assistant.observability import AssistantTelemetry
from app.assistant.providers.openai_responses import OpenAIResponsesModel
from app.assistant.runtime import (
    AssistantRuntimeConfig,
    ProductionLanguageModel,
    build_production_language_model,
)
from interfaces.api.service import TradingApiService


def _prompt() -> ModelPrompt:
    return ModelPrompt(
        query="Explain BTCUSD",
        intent=AssistantIntent.SYMBOL_EXPLANATION,
        system_instructions="Use grounded evidence only.",
        evidence=(
            EvidenceCitation(
                citation_id="BTCUSD:strategy:score",
                key="score",
                value="94",
                source="strategy",
                symbol="BTCUSD",
            ),
        ),
        symbol="BTCUSD",
    )


def test_openai_responses_adapter_extracts_visible_citations_and_usage() -> None:
    captured: dict[str, Any] = {}

    def transport(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "output_text": "BTCUSD score is 94 [BTCUSD:strategy:score].",
            "usage": {"input_tokens": 120, "output_tokens": 24},
        }

    model = OpenAIResponsesModel(
        api_key="test-key",
        model="gpt-5.6-luna",
        allowed_models=("gpt-5.6-luna",),
        transport=transport,
    )
    reply = model.generate(_prompt())

    assert reply.citations == ("BTCUSD:strategy:score",)
    assert reply.input_tokens == 120
    assert reply.output_tokens == 24
    assert reply.provider == "openai"
    assert captured["payload"]["model"] == "gpt-5.6-luna"
    assert captured["api_key"] == "test-key"


def test_openai_responses_adapter_rejects_model_outside_allowlist() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        OpenAIResponsesModel(
            api_key="test-key",
            model="unapproved-model",
            allowed_models=("gpt-5.6-luna",),
        )


def test_production_wrapper_records_content_free_success_metrics() -> None:
    class FakeModel:
        def generate(self, prompt: ModelPrompt) -> ModelReply:
            return ModelReply(
                text="Grounded [BTCUSD:strategy:score]",
                citations=("BTCUSD:strategy:score",),
                input_tokens=10,
                output_tokens=4,
            )

    telemetry = AssistantTelemetry()
    model = ProductionLanguageModel(
        FakeModel(),
        provider="fake",
        model="fake-1",
        telemetry=telemetry,
    )

    reply = model.generate(_prompt())
    snapshot = telemetry.snapshot()
    events = telemetry.events()

    assert reply.citations == ("BTCUSD:strategy:score",)
    assert snapshot.calls == 1
    assert snapshot.successes == 1
    assert snapshot.failures == 0
    assert snapshot.input_tokens == 10
    assert snapshot.output_tokens == 4
    assert events[0].evidence_count == 1
    assert not hasattr(events[0], "query")
    assert not hasattr(events[0], "api_key")


def test_production_wrapper_records_failure_and_opens_circuit() -> None:
    class FailingModel:
        def generate(self, prompt: ModelPrompt) -> ModelReply:
            raise RuntimeError("provider failure")

    telemetry = AssistantTelemetry()
    model = ProductionLanguageModel(
        FailingModel(),
        provider="fake",
        model="fake-1",
        telemetry=telemetry,
        circuit_failure_threshold=1,
        circuit_recovery_seconds=60,
    )

    with pytest.raises(RuntimeError, match="provider failure"):
        model.generate(_prompt())

    assert model.circuit_open is True
    assert telemetry.snapshot().failures == 1
    assert telemetry.events()[0].error_type == "RuntimeError"


def test_runtime_is_deterministic_only_when_llm_is_disabled() -> None:
    telemetry = AssistantTelemetry()
    config = AssistantRuntimeConfig(enabled=False)

    assert build_production_language_model(config, telemetry) is None


def test_runtime_fails_closed_when_enabled_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = AssistantRuntimeConfig(enabled=True)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_production_language_model(config, AssistantTelemetry())


def test_api_exposes_read_only_assistant_metrics() -> None:
    telemetry = AssistantTelemetry()
    service = TradingApiService(assistant_metrics_provider=telemetry.snapshot)

    response = service.assistant_metrics()

    assert response.status_code == 200
    assert response.body["assistant_metrics"]["calls"] == 0
    assert "events" not in response.body["assistant_metrics"]
