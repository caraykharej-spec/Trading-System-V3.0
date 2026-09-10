from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from app.application.strategy_pipeline import StrategyPipeline
from app.context.models import ContextAssessment
from app.core.models import Position
from app.portfolio.account import Account
from app.portfolio.correlation import correlation_risk_multiplier
from app.portfolio.portfolio_engine import PortfolioAssessment, PortfolioPolicy, assess_portfolio
from app.risk.risk_engine import RiskAssessment, assess_risk
from app.risk.risk_policy import RiskPolicy
from app.strategy.strategy_engine import StrategySignal
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import Instrument


@dataclass(frozen=True)
class RiskContext:
    account: Account
    positions: list[Position]
    instrument: Instrument
    contract: ContractSpec
    leverage: Decimal
    provider: str | None = None
    correlation: Decimal = Decimal("0")


RiskContextLoader = Callable[[str], RiskContext]
ContextLoader = Callable[[str], ContextAssessment]


@dataclass(frozen=True)
class GatedOpportunity:
    signal: StrategySignal
    risk: RiskAssessment
    portfolio: PortfolioAssessment
    rank: int


@dataclass(frozen=True)
class OpportunityPipelineResult:
    evaluated: int
    strategy_qualified: int
    context_rejected: int
    risk_rejected: int
    portfolio_rejected: int
    qualified: tuple[GatedOpportunity, ...]


class OpportunityPipeline:
    """Apply Strategy -> Context -> Risk -> Portfolio hard gates before Top-N ranking."""

    def __init__(self, strategy_pipeline: StrategyPipeline, risk_context_loader: RiskContextLoader, *, context_loader: ContextLoader | None = None, risk_policy: RiskPolicy = RiskPolicy(), portfolio_policy: PortfolioPolicy | None = None) -> None:
        self.strategy_pipeline = strategy_pipeline
        self.risk_context_loader = risk_context_loader
        self.context_loader = context_loader
        self.risk_policy = risk_policy
        self.portfolio_policy = portfolio_policy or PortfolioPolicy(max_aggregate_risk_percent=risk_policy.max_aggregate_open_risk_percent, max_correlated_risk_percent=risk_policy.max_correlated_risk_percent, max_futures_capital_percent=risk_policy.max_futures_capital_percent)

    def evaluate(self, symbols: Iterable[str], top_n: int = 10) -> OpportunityPipelineResult:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        evaluated, signals = self.strategy_pipeline.evaluate_all(symbols)
        gated: list[tuple[StrategySignal, RiskAssessment, PortfolioAssessment]] = []
        context_rejected = risk_rejected = portfolio_rejected = 0
        for signal in signals:
            if self.context_loader is not None:
                context = self.context_loader(signal.symbol)
                if context.blocking or context.delay:
                    context_rejected += 1
                    continue
            context = self.risk_context_loader(signal.symbol)
            existing_risk = context.account.aggregate_open_risk(context.positions)
            correlated_open_risk = existing_risk * correlation_risk_multiplier(context.correlation)
            risk = assess_risk(account=context.account, positions=context.positions, signal=signal, instrument=context.instrument, contract=context.contract, leverage=context.leverage, policy=self.risk_policy, provider=context.provider, correlated_open_risk=correlated_open_risk)
            if not risk.approved:
                risk_rejected += 1
                continue
            portfolio = assess_portfolio(equity=context.account.equity, positions=context.positions, new_risk=risk.new_risk, new_notional=risk.total_amount, correlation=context.correlation, policy=self.portfolio_policy, new_futures_capital=risk.total_amount if context.leverage > 1 else Decimal("0"))
            if not portfolio.approved:
                portfolio_rejected += 1
                continue
            gated.append((signal, risk, portfolio))
        gated.sort(key=lambda item: (item[0].score, item[0].confidence, item[0].rr), reverse=True)
        selected = tuple(GatedOpportunity(signal, risk, portfolio, rank) for rank, (signal, risk, portfolio) in enumerate(gated[:top_n], start=1))
        return OpportunityPipelineResult(evaluated, len(signals), context_rejected, risk_rejected, portfolio_rejected, selected)
