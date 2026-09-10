from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json

from app.context.models import ContextAssessment
from app.portfolio.portfolio_engine import PortfolioAssessment
from app.risk.risk_engine import RiskAssessment
from app.strategy.strategy_engine import StrategySignal


@dataclass(frozen=True)
class DecisionEvidence:
    """Immutable decision provenance carried from strategy through portfolio gates."""

    symbol: str
    direction: str
    setup: str
    score: Decimal
    confidence: Decimal
    planned_rr: Decimal
    score_components: dict[str, Decimal]
    strategy_quality: dict[str, Decimal]
    market_regime: str
    htf_trend: str
    structure_state: str
    context_news: str
    context_event: str
    context_blocking: bool
    context_delay: bool
    provider: str | None
    new_risk: Decimal
    risk_percent: Decimal
    aggregate_risk: Decimal
    portfolio_aggregate_risk_percent: Decimal
    correlated_risk_percent: Decimal
    futures_capital_percent: Decimal
    reserved_pending_risk: Decimal

    @classmethod
    def build(
        cls,
        *,
        signal: StrategySignal,
        context: ContextAssessment | None,
        risk: RiskAssessment,
        portfolio: PortfolioAssessment,
        provider: str | None,
    ) -> "DecisionEvidence":
        breakdown = signal.score_breakdown
        score_components = {
            "htf_trend": breakdown.htf_trend,
            "structure": breakdown.structure,
            "setup": breakdown.setup,
            "confirmation": breakdown.confirmation,
            "liquidity": breakdown.liquidity,
            "volatility": breakdown.volatility,
            "rr_quality": breakdown.rr_quality,
        }
        strategy_quality: dict[str, Decimal] = {}
        market_regime = "UNKNOWN"
        htf_trend = "UNKNOWN"
        structure_state = "UNKNOWN"
        if signal.evidence is not None:
            strategy_quality = {
                "data_quality": signal.evidence.data_quality,
                "htf_alignment": signal.evidence.htf_alignment_quality,
                "structure": signal.evidence.structure_quality,
                "setup": signal.evidence.setup_quality,
                "confirmation": signal.evidence.confirmation_quality,
                "liquidity": signal.evidence.liquidity_quality,
                "volatility": signal.evidence.volatility_quality,
                "rr": signal.evidence.rr_quality,
            }
            market_regime = signal.evidence.market_regime
            htf_trend = signal.evidence.htf_trend
            structure_state = signal.evidence.structure_state
        return cls(
            symbol=signal.symbol,
            direction=signal.direction,
            setup=signal.setup,
            score=signal.score,
            confidence=signal.confidence,
            planned_rr=signal.rr,
            score_components=score_components,
            strategy_quality=strategy_quality,
            market_regime=market_regime,
            htf_trend=htf_trend,
            structure_state=structure_state,
            context_news=context.news.value if context is not None else "UNKNOWN",
            context_event=context.event.value if context is not None else "NONE",
            context_blocking=context.blocking if context is not None else False,
            context_delay=context.delay if context is not None else False,
            provider=provider,
            new_risk=risk.new_risk,
            risk_percent=risk.risk_percent,
            aggregate_risk=risk.aggregate_risk,
            portfolio_aggregate_risk_percent=portfolio.aggregate_risk_percent,
            correlated_risk_percent=portfolio.correlated_risk_percent,
            futures_capital_percent=portfolio.futures_capital_percent,
            reserved_pending_risk=portfolio.reserved_pending_risk,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "setup": self.setup,
            "score": str(self.score),
            "confidence": str(self.confidence),
            "planned_rr": str(self.planned_rr),
            "market_regime": self.market_regime,
            "htf_trend": self.htf_trend,
            "structure_state": self.structure_state,
            "score_components": {
                key: str(value) for key, value in self.score_components.items()
            },
            "strategy_quality": {
                key: str(value) for key, value in self.strategy_quality.items()
            },
            "context": {
                "news": self.context_news,
                "event": self.context_event,
                "blocking": self.context_blocking,
                "delay": self.context_delay,
            },
            "provider": self.provider,
            "risk": {
                "new_risk": str(self.new_risk),
                "risk_percent": str(self.risk_percent),
                "aggregate_risk": str(self.aggregate_risk),
                "reserved_pending_risk": str(self.reserved_pending_risk),
            },
            "portfolio": {
                "aggregate_risk_percent": str(self.portfolio_aggregate_risk_percent),
                "correlated_risk_percent": str(self.correlated_risk_percent),
                "futures_capital_percent": str(self.futures_capital_percent),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
