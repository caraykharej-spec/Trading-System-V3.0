from __future__ import annotations

from app.assistant import (
    AnswerMode,
    AssistantIntent,
    AssistantOrchestrator,
    InMemoryConversationStore,
    ModelPrompt,
    ModelReply,
)
from app.copilot.models import (
    CopilotItemBrief,
    CopilotMarketBrief,
    CopilotStatus,
    EvidenceFact,
)
from interfaces.api.service import TradingApiService


class FakeModel:
    def __init__(self, reply: ModelReply) -> None:
        self.reply = reply
        self.prompts: list[ModelPrompt] = []

    def generate(self, prompt: ModelPrompt) -> ModelReply:
        self.prompts.append(prompt)
        return self.reply


def _brief() -> CopilotMarketBrief:
    qualified = CopilotItemBrief(
        symbol="BTCUSD",
        status=CopilotStatus.QUALIFIED,
        title="BTCUSD qualified opportunity",
        narrative=("BTCUSD passed deterministic gates.",),
        facts=(
            EvidenceFact("score", "94", "strategy"),
            EvidenceFact("confidence", "92", "strategy"),
            EvidenceFact("risk_percent", "1", "risk"),
            EvidenceFact("correlated_risk_percent", "1.2", "portfolio"),
            EvidenceFact("provider", "STORM", "data"),
        ),
        rank=1,
    )
    rejected = CopilotItemBrief(
        symbol="ETHUSD",
        status=CopilotStatus.REJECTED,
        title="ETHUSD rejected",
        narrative=("ETHUSD did not pass the risk gate.",),
        facts=(EvidenceFact("gate_stage", "RISK", "application_gate_trace"),),
        reasons=("aggregate open-risk budget exhausted",),
    )
    return CopilotMarketBrief(
        evaluated=2,
        strategy_qualified=2,
        context_rejected=0,
        risk_rejected=1,
        portfolio_rejected=0,
        items=(qualified, rejected),
    )


def test_orchestrator_without_model_returns_grounded_deterministic_answer() -> None:
    assistant = AssistantOrchestrator(_brief)

    response = assistant.ask("Explain BTCUSD")

    assert response.intent is AssistantIntent.SYMBOL_EXPLANATION
    assert response.mode is AnswerMode.DETERMINISTIC
    assert response.symbol == "BTCUSD"
    assert response.execution_authority is False
    assert response.model_used is False
    assert any(item.citation_id == "BTCUSD:strategy:score" for item in response.citations)
    assert "target_price" not in {item.key for item in response.citations}


def test_valid_model_reply_requires_visible_allowed_citations() -> None:
    citation_id = "BTCUSD:strategy:score"
    model = FakeModel(
        ModelReply(
            text=f"BTCUSD has recorded score 94 [{citation_id}].",
            citations=(citation_id,),
        )
    )
    assistant = AssistantOrchestrator(_brief, model=model)

    response = assistant.ask("Explain BTCUSD")

    assert response.mode is AnswerMode.MODEL
    assert response.model_used is True
    assert response.citations[0].citation_id == citation_id
    assert model.prompts[0].system_instructions
    assert model.prompts[0].evidence


def test_model_reply_with_fake_citation_fails_closed_to_deterministic_answer() -> None:
    model = FakeModel(
        ModelReply(
            text="Invented fact [BTCUSD:strategy:target_price].",
            citations=("BTCUSD:strategy:target_price",),
        )
    )
    assistant = AssistantOrchestrator(_brief, model=model)

    response = assistant.ask("Explain BTCUSD")

    assert response.mode is AnswerMode.DETERMINISTIC
    assert response.model_used is False
    assert "model_output_rejected" in response.unknowns
    assert all(item.key != "target_price" for item in response.citations)


def test_model_execution_instruction_is_rejected_even_with_valid_citation() -> None:
    citation_id = "BTCUSD:strategy:score"
    model = FakeModel(
        ModelReply(
            text=f"Buy now because the score is 94 [{citation_id}].",
            citations=(citation_id,),
        )
    )
    assistant = AssistantOrchestrator(_brief, model=model)

    response = assistant.ask("Explain BTCUSD")

    assert response.model_used is False
    assert response.execution_authority is False
    assert "model_output_rejected" in response.unknowns


def test_rejection_question_uses_recorded_gate_reason() -> None:
    assistant = AssistantOrchestrator(_brief)

    response = assistant.ask("Why was ETHUSD rejected?")

    assert response.intent is AssistantIntent.REJECTION_REASON
    assert response.symbol == "ETHUSD"
    assert "aggregate open-risk budget exhausted" in response.text
    assert any(item.source == "gate_reason" for item in response.citations)


def test_unknown_question_does_not_invent_market_data() -> None:
    assistant = AssistantOrchestrator(_brief)

    response = assistant.ask("Tell me tomorrow's exact closing price")

    assert response.intent is AssistantIntent.UNKNOWN
    assert response.mode is AnswerMode.UNKNOWN
    assert response.grounded is False
    assert response.citations == ()
    assert response.text.startswith("UNKNOWN")


def test_bounded_session_context_resolves_symbol_follow_up() -> None:
    store = InMemoryConversationStore(max_turns=2)
    assistant = AssistantOrchestrator(_brief, sessions=store)

    assistant.ask("Explain BTCUSD", session_id="mobile_1")
    response = assistant.ask("What about its risk?", session_id="mobile_1")
    assistant.ask("market brief", session_id="mobile_1")

    assert response.intent is AssistantIntent.RISK_SUMMARY
    assert response.symbol == "BTCUSD"
    assert len(store.history("mobile_1")) == 2
    assert store.last_symbol("mobile_1") == "BTCUSD"


def test_invalid_session_id_is_rejected() -> None:
    assistant = AssistantOrchestrator(_brief)

    try:
        assistant.ask("Explain BTCUSD", session_id="invalid session id")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("invalid session id should fail")


def test_api_exposes_grounded_assistant_query_without_execution_authority() -> None:
    assistant = AssistantOrchestrator(_brief)
    service = TradingApiService(
        assistant_query_provider=lambda query, session_id: assistant.ask(
            query, session_id=session_id
        )
    )

    response = service.assistant_query("Explain BTCUSD", "api_session")
    invalid = service.assistant_query(" ")

    assert response.status_code == 200
    assert response.body["assistant"]["symbol"] == "BTCUSD"
    assert response.body["assistant"]["execution_authority"] is False
    assert invalid.status_code == 400
