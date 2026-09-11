from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class ValidationDecision(str, Enum):
    QUALIFIED = "QUALIFIED"
    HOLD = "HOLD"


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    passed: bool
    details: str
    critical: bool = True


@dataclass(frozen=True)
class StrategyValidationPolicy:
    min_oos_trades: int = 20
    min_oos_return_percent: Decimal = Decimal("0")
    min_oos_profit_factor: Decimal = Decimal("1.05")
    max_oos_drawdown_percent: Decimal = Decimal("25")
    min_walk_forward_windows: int = 3
    min_profitable_walk_forward_ratio: Decimal = Decimal("0.60")
    min_monte_carlo_median_return_percent: Decimal = Decimal("0")
    max_monte_carlo_worst_drawdown_percent: Decimal = Decimal("40")
    max_cost_stress_degradation_percent: Decimal = Decimal("40")
    max_parameter_normalized_spread: Decimal = Decimal("0.35")
    min_regime_trade_count: int = 5
    min_qualified_regimes: int = 2
    min_forward_observations: int = 20
    min_forward_hit_rate_percent: Decimal = Decimal("50")
    min_forward_mean_return_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        count_fields = (
            self.min_oos_trades,
            self.min_walk_forward_windows,
            self.min_regime_trade_count,
            self.min_qualified_regimes,
            self.min_forward_observations,
        )
        if any(value < 0 for value in count_fields):
            raise ValueError("validation minimum counts must be non-negative")
        bounded = (
            self.max_oos_drawdown_percent,
            self.min_profitable_walk_forward_ratio * Decimal("100"),
            self.max_monte_carlo_worst_drawdown_percent,
            self.max_cost_stress_degradation_percent,
            self.max_parameter_normalized_spread * Decimal("100"),
            self.min_forward_hit_rate_percent,
        )
        if any(value < 0 or value > 100 for value in bounded):
            raise ValueError("validation percentage thresholds must be in [0, 100]")


@dataclass(frozen=True)
class StrategyQualificationReport:
    checks: tuple[ValidationCheck, ...]

    @property
    def decision(self) -> ValidationDecision:
        if self.checks and all(check.passed or not check.critical for check in self.checks):
            return ValidationDecision.QUALIFIED
        return ValidationDecision.HOLD

    @property
    def qualified(self) -> bool:
        return self.decision is ValidationDecision.QUALIFIED
