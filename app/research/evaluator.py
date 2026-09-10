from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig
from app.backtest.portfolio import PortfolioBacktestEngine
from app.backtest.walk_forward import WalkForwardRunner
from app.data.market_data import Candle
from app.strategy.rules import DEFAULT_RULES, StrategyRules

from .models import ParameterSet, ResearchEvaluation
from .objectives import (
    summarize_backtest,
    summarize_backtests,
    summarize_portfolio_backtest,
)
from .parameter_space import StrategyRuleParameterPolicy


def strategy_rules_from_parameters(
    parameters: ParameterSet,
    *,
    baseline: StrategyRules = DEFAULT_RULES,
    policy: StrategyRuleParameterPolicy | None = None,
) -> StrategyRules:
    active_policy = policy or StrategyRuleParameterPolicy(baseline)
    active_policy.validate_set(parameters)
    values = parameters.as_dict()

    def decimal_value(name: str, fallback: Decimal) -> Decimal:
        value = values.get(name)
        if value is None:
            return fallback
        if not isinstance(value, Decimal):
            raise TypeError(f"strategy parameter {name} must be Decimal")
        return value

    return StrategyRules(
        min_rr=decimal_value("min_rr", baseline.min_rr),
        min_score=decimal_value("min_score", baseline.min_score),
        min_confidence=decimal_value("min_confidence", baseline.min_confidence),
    )


@dataclass
class BacktestResearchEvaluator:
    symbol: str
    candles_by_timeframe: dict[str, list[Candle]]
    config: BacktestConfig = BacktestConfig()
    baseline_rules: StrategyRules = DEFAULT_RULES
    evaluation_start: datetime | None = None

    def __call__(self, parameters: ParameterSet) -> ResearchEvaluation:
        rules = strategy_rules_from_parameters(parameters, baseline=self.baseline_rules)
        engine = BacktestEngine(config=self.config, rules=rules)
        result = engine.run(
            self.symbol,
            self.candles_by_timeframe,
            evaluation_start=self.evaluation_start,
        )
        return ResearchEvaluation(summary=summarize_backtest(result))


@dataclass
class PortfolioResearchEvaluator:
    candles_by_symbol: dict[str, dict[str, list[Candle]]]
    config: BacktestConfig = BacktestConfig()
    correlations: dict[tuple[str, str], Decimal] | None = None
    baseline_rules: StrategyRules = DEFAULT_RULES

    def __call__(self, parameters: ParameterSet) -> ResearchEvaluation:
        rules = strategy_rules_from_parameters(parameters, baseline=self.baseline_rules)
        result = PortfolioBacktestEngine(
            config=self.config,
            correlations=self.correlations,
            rules=rules,
        ).run(self.candles_by_symbol)
        return ResearchEvaluation(summary=summarize_portfolio_backtest(result))


@dataclass
class WalkForwardResearchEvaluator:
    symbol: str
    candles_by_timeframe: dict[str, list[Candle]]
    train_size: int
    test_size: int
    step: int | None = None
    config: BacktestConfig = BacktestConfig()
    baseline_rules: StrategyRules = DEFAULT_RULES

    def __call__(self, parameters: ParameterSet) -> ResearchEvaluation:
        rules = strategy_rules_from_parameters(parameters, baseline=self.baseline_rules)
        result = WalkForwardRunner(config=self.config, rules=rules).run(
            self.symbol,
            self.candles_by_timeframe,
            train_size=self.train_size,
            test_size=self.test_size,
            step=self.step,
        )
        windows = tuple(summarize_backtest(item) for item in result.results)
        return ResearchEvaluation(
            summary=summarize_backtests(result.results),
            windows=windows,
        )
