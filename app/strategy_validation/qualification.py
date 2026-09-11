from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Self

from app.backtest.models import BacktestResult
from app.backtest.monte_carlo import MonteCarloResult
from app.backtest.walk_forward import WalkForwardResult

from .cost_stress import CostStressReport
from .forward import ForwardValidationReport
from .models import (
    StrategyQualificationReport,
    StrategyValidationPolicy,
    ValidationCheck,
)
from .regime import RegimeValidationReport
from .stability import ParameterStabilityReport

if TYPE_CHECKING:
    from .calibration import ThresholdCalibrationReport


@dataclass(frozen=True)
class StrategyValidationEvidence:
    holdout: BacktestResult | None = None
    walk_forward: WalkForwardResult | None = None
    monte_carlo: MonteCarloResult | None = None
    cost_stress: CostStressReport | None = None
    parameter_stability: ParameterStabilityReport | None = None
    regime: RegimeValidationReport | None = None
    forward: ForwardValidationReport | None = None


class StrategyQualificationEngine:
    """Fail-closed qualification gate for strategy and signal evidence."""

    def __init__(self, policy: StrategyValidationPolicy | None = None) -> None:
        self.policy = policy or StrategyValidationPolicy()

    @classmethod
    def from_calibration(cls, report: ThresholdCalibrationReport) -> Self:
        """Build an engine only from a successfully calibrated policy."""
        return cls(report.require_policy())

    def evaluate(self, evidence: StrategyValidationEvidence) -> StrategyQualificationReport:
        checks = (
            self._check_holdout(evidence.holdout),
            self._check_walk_forward(evidence.walk_forward),
            self._check_monte_carlo(evidence.monte_carlo),
            self._check_cost_stress(evidence.cost_stress),
            self._check_parameter_stability(evidence.parameter_stability),
            self._check_regimes(evidence.regime),
            self._check_forward(evidence.forward),
        )
        return StrategyQualificationReport(checks=checks)

    def _check_holdout(self, result: BacktestResult | None) -> ValidationCheck:
        if result is None:
            return ValidationCheck("holdout_oos", False, "holdout evidence is missing")
        profit_factor = result.profit_factor
        passed = (
            len(result.trades) >= self.policy.min_oos_trades
            and result.total_return_percent >= self.policy.min_oos_return_percent
            and result.max_drawdown_percent <= self.policy.max_oos_drawdown_percent
            and profit_factor is not None
            and profit_factor >= self.policy.min_oos_profit_factor
        )
        return ValidationCheck(
            "holdout_oos",
            passed,
            (
                f"trades={len(result.trades)} return={result.total_return_percent}% "
                f"drawdown={result.max_drawdown_percent}% profit_factor={profit_factor}"
            ),
        )

    def _check_walk_forward(self, result: WalkForwardResult | None) -> ValidationCheck:
        if result is None:
            return ValidationCheck("walk_forward", False, "walk-forward evidence is missing")
        count = len(result.results)
        profitable = sum(1 for item in result.results if item.total_return_percent > 0)
        ratio = Decimal(profitable) / Decimal(count) if count else Decimal("0")
        passed = (
            count >= self.policy.min_walk_forward_windows
            and ratio >= self.policy.min_profitable_walk_forward_ratio
        )
        return ValidationCheck(
            "walk_forward",
            passed,
            f"windows={count} profitable_ratio={ratio}",
        )

    def _check_monte_carlo(self, result: MonteCarloResult | None) -> ValidationCheck:
        if result is None:
            return ValidationCheck("monte_carlo", False, "Monte Carlo evidence is missing")
        passed = (
            result.simulations > 0
            and result.median_return_percent
            >= self.policy.min_monte_carlo_median_return_percent
            and result.worst_max_drawdown_percent
            <= self.policy.max_monte_carlo_worst_drawdown_percent
        )
        return ValidationCheck(
            "monte_carlo",
            passed,
            (
                f"simulations={result.simulations} "
                f"median_return={result.median_return_percent}% "
                f"worst_drawdown={result.worst_max_drawdown_percent}%"
            ),
        )

    def _check_cost_stress(self, report: CostStressReport | None) -> ValidationCheck:
        if report is None:
            return ValidationCheck("cost_stress", False, "cost-stress evidence is missing")
        worst = report.worst_return_degradation_percent
        passed = (
            bool(report.outcomes)
            and worst <= self.policy.max_cost_stress_degradation_percent
        )
        return ValidationCheck(
            "cost_stress",
            passed,
            f"worst_return_degradation={worst}% scenarios={len(report.outcomes)}",
        )

    def _check_parameter_stability(
        self,
        report: ParameterStabilityReport | None,
    ) -> ValidationCheck:
        if report is None:
            return ValidationCheck(
                "parameter_stability",
                False,
                "parameter-stability evidence is missing",
            )
        passed = (
            report.stable
            and report.max_normalized_spread <= self.policy.max_parameter_normalized_spread
            and report.feasible_trial_ratio >= self.policy.min_feasible_trial_ratio
        )
        return ValidationCheck(
            "parameter_stability",
            passed,
            (
                f"feasible_trial_ratio={report.feasible_trial_ratio} "
                f"max_normalized_spread={report.max_normalized_spread}"
            ),
        )

    def _check_regimes(self, report: RegimeValidationReport | None) -> ValidationCheck:
        if report is None:
            return ValidationCheck("regime_coverage", False, "regime evidence is missing")
        qualified = report.qualified_regime_count(
            min_trades=self.policy.min_regime_trade_count,
            min_profit_factor=self.policy.min_oos_profit_factor,
        )
        return ValidationCheck(
            "regime_coverage",
            qualified >= self.policy.min_qualified_regimes,
            f"qualified_regimes={qualified} total_regimes={len(report.regimes)}",
        )

    def _check_forward(self, report: ForwardValidationReport | None) -> ValidationCheck:
        if report is None:
            return ValidationCheck("forward_validation", False, "forward evidence is missing")
        passed = (
            report.resolved_observations >= self.policy.min_forward_observations
            and report.hit_rate_percent >= self.policy.min_forward_hit_rate_percent
            and report.mean_return_percent >= self.policy.min_forward_mean_return_percent
        )
        return ValidationCheck(
            "forward_validation",
            passed,
            (
                f"resolved={report.resolved_observations} "
                f"hit_rate={report.hit_rate_percent}% "
                f"mean_return={report.mean_return_percent}%"
            ),
        )
