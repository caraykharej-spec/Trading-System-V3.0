from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Callable, Iterable

from app.application.decision_evidence import DecisionEvidence
from app.application.strategy_pipeline import StrategyPipeline
from app.context.models import ContextAssessment
from app.core.models import Position
from app.portfolio.account import Account
from app.portfolio.correlation import CorrelationMatrix, correlation_risk_multiplier
from app.portfolio.portfolio_engine import PortfolioAssessment, PortfolioPolicy, assess_portfolio
from app.risk.risk_engine import RiskAssessment, assess_risk
from app.risk.risk_policy import RiskPolicy
from app.strategy.strategy_engine import StrategySignal
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import Instrument


class GateStage(str, Enum):
    STRATEGY = "STRATEGY"
    CONTEXT = "CONTEXT"
    RISK = "RISK"
    PORTFOLIO = "PORTFOLIO"


class GateOutcome(str, Enum):
    NO_TRADE = "NO_TRADE"
    HOLD = "HOLD"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class GateRejection:
    symbol: str
    stage: GateStage
    outcome: GateOutcome
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskContext:
    account: Account
    positions: list[Position]
    instrument: Instrument
    contract: ContractSpec
    leverage: Decimal
    provider: str | None = None
    correlation: Decimal = Decimal("0")
    reserved_pending_risk: Decimal = Decimal("0")
    correlation_matrix: CorrelationMatrix | None = None


RiskContextLoader = Callable[[str], RiskContext]
ContextLoader = Callable[[str], ContextAssessment]


@dataclass(frozen=True)
class GatedOpportunity:
    signal: StrategySignal
    risk: RiskAssessment
    portfolio: PortfolioAssessment
    rank: int
    evidence: DecisionEvidence | None = None


@dataclass(frozen=True)
class MarketEvaluation:
    symbol: str
    status: str
    gate_stage: str
    rank: int | None = None
    is_top_10: bool = False
    direction: str | None = None
    score: Decimal | None = None
    confidence: Decimal | None = None
    entry: Decimal | None = None
    stop_loss: Decimal | None = None
    target: Decimal | None = None
    rr: Decimal | None = None
    stop_loss_source: str | None = None
    stop_loss_buffer: Decimal | None = None
    score_components: dict[str, Decimal] | None = None
    news_impact: str = "UNKNOWN"
    event_importance: str = "NONE"
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpportunityPipelineResult:
    evaluated: int
    strategy_qualified: int
    context_rejected: int
    risk_rejected: int
    portfolio_rejected: int
    qualified: tuple[GatedOpportunity, ...]
    rejections: tuple[GateRejection, ...] = ()
    all_evaluations: tuple[MarketEvaluation, ...] = ()


class OpportunityPipeline:
    """Apply Strategy -> Context -> Risk -> Portfolio hard gates before Top-N ranking."""

    def __init__(
        self,
        strategy_pipeline: StrategyPipeline,
        risk_context_loader: RiskContextLoader,
        *,
        context_loader: ContextLoader | None = None,
        risk_policy: RiskPolicy = RiskPolicy(),
        portfolio_policy: PortfolioPolicy | None = None,
    ) -> None:
        self.strategy_pipeline = strategy_pipeline
        self.risk_context_loader = risk_context_loader
        self.context_loader = context_loader
        self.risk_policy = risk_policy
        self.portfolio_policy = portfolio_policy or PortfolioPolicy(
            max_aggregate_risk_percent=risk_policy.max_aggregate_open_risk_percent,
            max_correlated_risk_percent=risk_policy.max_correlated_risk_percent,
            max_futures_capital_percent=risk_policy.max_futures_capital_percent,
        )

    def evaluate(self, symbols: Iterable[str], top_n: int = 10) -> OpportunityPipelineResult:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        evaluated, signals, strategy_rejections = (
            self.strategy_pipeline.evaluate_all_with_rejections(symbols)
        )
        gated: list[
            tuple[StrategySignal, RiskAssessment, PortfolioAssessment, DecisionEvidence]
        ] = []
        rejections: list[GateRejection] = [
            GateRejection(
                symbol=item.symbol,
                stage=GateStage.STRATEGY,
                outcome=GateOutcome.NO_TRADE,
                reasons=item.reasons,
            )
            for item in strategy_rejections
        ]
        evaluations: dict[str, MarketEvaluation] = {
            item.symbol: MarketEvaluation(
                symbol=item.symbol,
                status=GateOutcome.NO_TRADE.value,
                gate_stage=GateStage.STRATEGY.value,
                reasons=item.reasons,
            )
            for item in strategy_rejections
        }
        contexts: dict[str, ContextAssessment] = {}
        context_rejected = risk_rejected = portfolio_rejected = 0

        for signal in signals:
            context_assessment: ContextAssessment | None = None
            if self.context_loader is not None:
                context_assessment = self.context_loader(signal.symbol)
                contexts[signal.symbol] = context_assessment
                if context_assessment.blocking or context_assessment.delay:
                    context_rejected += 1
                    reasons = context_assessment.reasons or ("context gate active",)
                    rejections.append(
                        GateRejection(
                            symbol=signal.symbol,
                            stage=GateStage.CONTEXT,
                            outcome=GateOutcome.HOLD,
                            reasons=reasons,
                        )
                    )
                    evaluations[signal.symbol] = self._evaluation(
                        signal,
                        GateOutcome.HOLD.value,
                        GateStage.CONTEXT.value,
                        reasons,
                        context=context_assessment,
                    )
                    continue

            risk_context = self.risk_context_loader(signal.symbol)
            existing_risk = risk_context.account.aggregate_open_risk(risk_context.positions)
            if risk_context.correlation_matrix is not None:
                matrix_exposure = risk_context.correlation_matrix.candidate_exposure(
                    candidate_symbol=signal.symbol,
                    new_risk=Decimal("0"),
                    positions=risk_context.positions,
                )
                correlated_open_risk = matrix_exposure.correlated_risk
            else:
                correlated_open_risk = existing_risk * correlation_risk_multiplier(
                    risk_context.correlation
                )

            risk = assess_risk(
                account=risk_context.account,
                positions=risk_context.positions,
                signal=signal,
                instrument=risk_context.instrument,
                contract=risk_context.contract,
                leverage=risk_context.leverage,
                policy=self.risk_policy,
                provider=risk_context.provider,
                correlated_open_risk=correlated_open_risk,
                reserved_pending_risk=risk_context.reserved_pending_risk,
            )
            if not risk.approved:
                risk_rejected += 1
                rejections.append(
                    GateRejection(
                        symbol=signal.symbol,
                        stage=GateStage.RISK,
                        outcome=GateOutcome.REJECTED,
                        reasons=risk.reasons or ("risk gate rejected candidate",),
                    )
                )
                evaluations[signal.symbol] = self._evaluation(
                    signal,
                    GateOutcome.REJECTED.value,
                    GateStage.RISK.value,
                    risk.reasons,
                    context=context_assessment,
                )
                continue

            portfolio = assess_portfolio(
                equity=risk_context.account.equity,
                positions=risk_context.positions,
                new_risk=risk.new_risk,
                new_notional=risk.total_amount,
                correlation=risk_context.correlation,
                policy=self.portfolio_policy,
                new_futures_capital=(
                    risk.total_amount if risk_context.leverage > 1 else Decimal("0")
                ),
                reserved_pending_risk=risk_context.reserved_pending_risk,
                candidate_symbol=signal.symbol,
                correlation_matrix=risk_context.correlation_matrix,
            )
            if not portfolio.approved:
                portfolio_rejected += 1
                rejections.append(
                    GateRejection(
                        symbol=signal.symbol,
                        stage=GateStage.PORTFOLIO,
                        outcome=GateOutcome.REJECTED,
                        reasons=portfolio.reasons or ("portfolio gate rejected candidate",),
                    )
                )
                evaluations[signal.symbol] = self._evaluation(
                    signal,
                    GateOutcome.REJECTED.value,
                    GateStage.PORTFOLIO.value,
                    portfolio.reasons,
                    context=context_assessment,
                )
                continue

            evidence = DecisionEvidence.build(
                signal=signal,
                context=context_assessment,
                risk=risk,
                portfolio=portfolio,
                provider=risk_context.provider,
            )
            gated.append((signal, risk, portfolio, evidence))

        gated.sort(
            key=lambda item: (item[0].score, item[0].confidence, item[0].rr), reverse=True
        )
        selected = tuple(
            GatedOpportunity(signal, risk, portfolio, rank, evidence)
            for rank, (signal, risk, portfolio, evidence) in enumerate(gated[:top_n], start=1)
        )
        for rank, (signal, _risk, _portfolio, _evidence) in enumerate(gated, start=1):
            evaluations[signal.symbol] = self._evaluation(
                signal,
                "QUALIFIED",
                "COMPLETE",
                (),
                rank=rank,
                is_top_10=rank <= 10,
                context=contexts.get(signal.symbol),
            )
        return OpportunityPipelineResult(
            evaluated=evaluated,
            strategy_qualified=len(signals),
            context_rejected=context_rejected,
            risk_rejected=risk_rejected,
            portfolio_rejected=portfolio_rejected,
            qualified=selected,
            rejections=tuple(rejections),
            all_evaluations=tuple(
                sorted(
                    evaluations.values(),
                    key=lambda item: (
                        item.rank is None,
                        item.rank if item.rank is not None else 10**9,
                        item.symbol,
                    ),
                )
            ),
        )

    @staticmethod
    def _evaluation(
        signal: StrategySignal,
        status: str,
        stage: str,
        reasons: tuple[str, ...],
        *,
        rank: int | None = None,
        is_top_10: bool = False,
        context: ContextAssessment | None = None,
    ) -> MarketEvaluation:
        breakdown = signal.score_breakdown
        return MarketEvaluation(
            symbol=signal.symbol,
            status=status,
            gate_stage=stage,
            rank=rank,
            is_top_10=is_top_10,
            direction=signal.direction,
            score=signal.score,
            confidence=signal.confidence,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            target=signal.target,
            rr=signal.rr,
            stop_loss_source=signal.stop_loss_source,
            stop_loss_buffer=signal.stop_loss_buffer,
            score_components={
                "htf_trend": breakdown.htf_trend,
                "structure": breakdown.structure,
                "setup": breakdown.setup,
                "confirmation": breakdown.confirmation,
                "liquidity": breakdown.liquidity,
                "volatility": breakdown.volatility,
                "rr_quality": breakdown.rr_quality,
            },
            news_impact=context.news.value if context is not None else "UNKNOWN",
            event_importance=context.event.value if context is not None else "NONE",
            reasons=reasons,
        )
