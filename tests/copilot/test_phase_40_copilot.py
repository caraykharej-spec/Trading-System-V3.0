from decimal import Decimal

from app.application.decision_evidence import DecisionEvidence
from app.application.opportunity_pipeline import (
    GateOutcome,
    GateRejection,
    GateStage,
    OpportunityPipelineResult,
)
from app.application.strategy_pipeline import StrategyPipeline
from app.copilot import CopilotExplainer, CopilotStatus
from interfaces.api.service import TradingApiService


def _evidence() -> DecisionEvidence:
    return DecisionEvidence(
        symbol="BTCUSD",
        direction="LONG",
        setup="TREND_PULLBACK",
        score=Decimal("94"),
        confidence=Decimal("92"),
        planned_rr=Decimal("2.8"),
        score_components={"setup": Decimal("24")},
        strategy_quality={"data_quality": Decimal("95")},
        market_regime="TRENDING",
        htf_trend="BULLISH",
        structure_state="NEAR_SUPPORT",
        context_news="NEUTRAL",
        context_event="NONE",
        context_blocking=False,
        context_delay=False,
        provider="STORM",
        new_risk=Decimal("10"),
        risk_percent=Decimal("1"),
        aggregate_risk=Decimal("20"),
        portfolio_aggregate_risk_percent=Decimal("2"),
        correlated_risk_percent=Decimal("1.2"),
        futures_capital_percent=Decimal("20"),
        reserved_pending_risk=Decimal("0"),
    )


def test_copilot_explains_only_recorded_evidence() -> None:
    brief = CopilotExplainer().explain_evidence(_evidence(), rank=1)

    assert brief.status is CopilotStatus.QUALIFIED
    assert brief.execution_authority is False
    assert brief.rank == 1
    facts = {fact.key: fact.value for fact in brief.facts}
    assert facts["score"] == "94"
    assert facts["confidence"] == "92"
    assert facts["provider"] == "STORM"
    assert "target_price" not in facts


def test_copilot_preserves_gate_rejection_reason() -> None:
    rejection = GateRejection(
        symbol="ETHUSD",
        stage=GateStage.RISK,
        outcome=GateOutcome.REJECTED,
        reasons=("aggregate open-risk budget exhausted",),
    )

    brief = CopilotExplainer().explain_rejection(rejection)

    assert brief.status is CopilotStatus.REJECTED
    assert brief.reasons == ("aggregate open-risk budget exhausted",)
    assert brief.execution_authority is False


def test_market_brief_is_read_only_and_contains_rejections() -> None:
    result = OpportunityPipelineResult(
        evaluated=2,
        strategy_qualified=1,
        context_rejected=1,
        risk_rejected=0,
        portfolio_rejected=0,
        qualified=(),
        rejections=(
            GateRejection(
                symbol="BTCUSD",
                stage=GateStage.CONTEXT,
                outcome=GateOutcome.HOLD,
                reasons=("critical_event_window_active",),
            ),
        ),
    )

    brief = CopilotExplainer().market_brief(result)

    assert brief.execution_authority is False
    assert brief.items[0].status is CopilotStatus.HOLD
    assert brief.items[0].reasons == ("critical_event_window_active",)


def test_strategy_pipeline_retains_no_trade_reason() -> None:
    def loader(symbol: str):
        raise ValueError(f"No aligned HTF direction for {symbol}")

    pipeline = StrategyPipeline(loader)
    evaluated, signals, rejections = pipeline.evaluate_all_with_rejections(["BTCUSD"])

    assert evaluated == 1
    assert signals == ()
    assert rejections[0].symbol == "BTCUSD"
    assert "No aligned HTF direction" in rejections[0].reasons[0]


def test_api_exposes_read_only_copilot_callbacks() -> None:
    item = CopilotExplainer().explain_evidence(_evidence(), rank=1)
    market = OpportunityPipelineResult(
        evaluated=1,
        strategy_qualified=1,
        context_rejected=0,
        risk_rejected=0,
        portfolio_rejected=0,
        qualified=(),
    )
    market_brief = CopilotExplainer().market_brief(market)
    service = TradingApiService(
        copilot_brief_provider=lambda: market_brief,
        copilot_symbol_provider=lambda symbol: item if symbol == "BTCUSD" else None,
    )

    brief_response = service.assistant_brief()
    symbol_response = service.assistant_opportunity("btcusd")
    missing_response = service.assistant_opportunity("ethusd")

    assert brief_response.status_code == 200
    assert brief_response.body["assistant"]["execution_authority"] is False
    assert symbol_response.status_code == 200
    assert symbol_response.body["assistant"]["symbol"] == "BTCUSD"
    assert missing_response.status_code == 404
