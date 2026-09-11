from __future__ import annotations

from decimal import Decimal

from app.application.decision_evidence import DecisionEvidence
from app.application.opportunity_pipeline import (
    GateOutcome,
    GateRejection,
    GatedOpportunity,
    OpportunityPipelineResult,
)

from .models import CopilotItemBrief, CopilotMarketBrief, CopilotStatus, EvidenceFact


def _fact(key: str, value: object, source: str) -> EvidenceFact:
    return EvidenceFact(key=key, value=str(value), source=source)


def _status_from_outcome(outcome: GateOutcome) -> CopilotStatus:
    if outcome is GateOutcome.HOLD:
        return CopilotStatus.HOLD
    if outcome is GateOutcome.NO_TRADE:
        return CopilotStatus.NO_TRADE
    return CopilotStatus.REJECTED


class CopilotExplainer:
    """Deterministic, evidence-grounded explanation layer.

    The explainer does not calculate signals, approve risk, size positions, or
    submit orders. It only renders facts already produced by upstream domains.
    """

    def explain_evidence(
        self,
        evidence: DecisionEvidence,
        *,
        rank: int | None = None,
    ) -> CopilotItemBrief:
        facts = (
            _fact("direction", evidence.direction, "strategy"),
            _fact("setup", evidence.setup, "strategy"),
            _fact("score", evidence.score, "strategy"),
            _fact("confidence", evidence.confidence, "strategy"),
            _fact("planned_rr", evidence.planned_rr, "strategy"),
            _fact("market_regime", evidence.market_regime, "market"),
            _fact("htf_trend", evidence.htf_trend, "strategy"),
            _fact("structure_state", evidence.structure_state, "market"),
            _fact("context_news", evidence.context_news, "context"),
            _fact("context_event", evidence.context_event, "context"),
            _fact("risk_percent", evidence.risk_percent, "risk"),
            _fact("aggregate_risk", evidence.aggregate_risk, "risk"),
            _fact(
                "portfolio_aggregate_risk_percent",
                evidence.portfolio_aggregate_risk_percent,
                "portfolio",
            ),
            _fact(
                "correlated_risk_percent",
                evidence.correlated_risk_percent,
                "portfolio",
            ),
            _fact("futures_capital_percent", evidence.futures_capital_percent, "portfolio"),
            _fact("provider", evidence.provider or "UNKNOWN", "data"),
        )
        narrative = (
            f"{evidence.symbol} passed the strategy, context, risk, and portfolio gates.",
            (
                f"The qualified setup is {evidence.direction} {evidence.setup} with "
                f"score {evidence.score}, confidence {evidence.confidence}, and planned "
                f"R:R {evidence.planned_rr}."
            ),
            (
                f"Recorded risk is {evidence.risk_percent}% for the candidate and "
                f"{evidence.portfolio_aggregate_risk_percent}% aggregate portfolio risk."
            ),
        )
        return CopilotItemBrief(
            symbol=evidence.symbol,
            status=CopilotStatus.QUALIFIED,
            title=f"{evidence.symbol} qualified opportunity",
            narrative=narrative,
            facts=facts,
            rank=rank,
        )

    def explain_rejection(self, rejection: GateRejection) -> CopilotItemBrief:
        status = _status_from_outcome(rejection.outcome)
        facts = (
            _fact("gate_stage", rejection.stage.value, "application_gate_trace"),
            _fact("gate_outcome", rejection.outcome.value, "application_gate_trace"),
        )
        narrative = (
            f"{rejection.symbol} did not proceed beyond the {rejection.stage.value} gate.",
            "The reasons below are copied from deterministic upstream gate evidence.",
        )
        return CopilotItemBrief(
            symbol=rejection.symbol,
            status=status,
            title=f"{rejection.symbol} {status.value.lower()}",
            narrative=narrative,
            facts=facts,
            reasons=rejection.reasons,
        )

    def explain_opportunity(self, opportunity: GatedOpportunity) -> CopilotItemBrief:
        if opportunity.evidence is not None:
            return self.explain_evidence(opportunity.evidence, rank=opportunity.rank)

        signal = opportunity.signal
        risk = opportunity.risk
        portfolio = opportunity.portfolio
        facts = (
            _fact("direction", signal.direction, "strategy"),
            _fact("setup", signal.setup, "strategy"),
            _fact("score", signal.score, "strategy"),
            _fact("confidence", signal.confidence, "strategy"),
            _fact("planned_rr", signal.rr, "strategy"),
            _fact("risk_percent", risk.risk_percent, "risk"),
            _fact("aggregate_risk_percent", portfolio.aggregate_risk_percent, "portfolio"),
            _fact("correlated_risk_percent", portfolio.correlated_risk_percent, "portfolio"),
        )
        return CopilotItemBrief(
            symbol=signal.symbol,
            status=CopilotStatus.QUALIFIED,
            title=f"{signal.symbol} qualified opportunity",
            narrative=(
                "The opportunity is qualified, but immutable DecisionEvidence is unavailable.",
                "Only fields present on the qualified signal/risk/portfolio objects are shown.",
            ),
            facts=facts,
            rank=opportunity.rank,
        )

    def market_brief(self, result: OpportunityPipelineResult) -> CopilotMarketBrief:
        items = [self.explain_opportunity(item) for item in result.qualified]
        items.extend(self.explain_rejection(item) for item in result.rejections)
        return CopilotMarketBrief(
            evaluated=result.evaluated,
            strategy_qualified=result.strategy_qualified,
            context_rejected=result.context_rejected,
            risk_rejected=result.risk_rejected,
            portfolio_rejected=result.portfolio_rejected,
            items=tuple(items),
        )

    @staticmethod
    def find_symbol(brief: CopilotMarketBrief, symbol: str) -> CopilotItemBrief | None:
        target = symbol.strip().upper()
        if not target:
            return None
        return next((item for item in brief.items if item.symbol.upper() == target), None)


def decimal_or_unknown(value: Decimal | None) -> str:
    return str(value) if value is not None else "UNKNOWN"
