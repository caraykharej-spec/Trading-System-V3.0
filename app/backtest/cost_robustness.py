from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from app.backtest.costs import BacktestCostModel

MAX_COST_SCENARIOS = 512


@dataclass(frozen=True)
class CostAssumption:
    scenario_id: str
    fee_percent: Decimal
    funding_percent: Decimal
    slippage_percent: Decimal
    market_impact_percent: Decimal

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must be non-empty")
        values = (
            self.fee_percent,
            self.funding_percent,
            self.slippage_percent,
            self.market_impact_percent,
        )
        if any(not value.is_finite() for value in values):
            raise ValueError("cost assumptions must be finite")
        if self.fee_percent < 0:
            raise ValueError("fee_percent must be non-negative")
        if self.slippage_percent < 0:
            raise ValueError("slippage_percent must be non-negative")
        if self.market_impact_percent < 0:
            raise ValueError("market_impact_percent must be non-negative")

    @property
    def total_cost_percent(self) -> Decimal:
        return (
            self.fee_percent
            + self.funding_percent
            + self.slippage_percent
            + self.market_impact_percent
        )


@dataclass(frozen=True)
class CostRobustnessThresholds:
    min_scenario_count: int = 4
    min_stable_scenario_fraction: Decimal = Decimal("1")
    max_net_edge_degradation_percent: Decimal = Decimal("60")
    min_net_edge_percent: Decimal = Decimal("0")
    max_scenarios: int = MAX_COST_SCENARIOS

    def __post_init__(self) -> None:
        if self.min_scenario_count < 1:
            raise ValueError("min_scenario_count must be positive")
        if self.max_scenarios < 1 or self.max_scenarios > 100_000:
            raise ValueError("max_scenarios must be in [1, 100000]")
        if self.min_scenario_count > self.max_scenarios:
            raise ValueError("min_scenario_count must not exceed max_scenarios")
        decimals = (
            self.min_stable_scenario_fraction,
            self.max_net_edge_degradation_percent,
            self.min_net_edge_percent,
        )
        if any(not value.is_finite() for value in decimals):
            raise ValueError("cost robustness thresholds must be finite")
        if not Decimal("0") <= self.min_stable_scenario_fraction <= Decimal("1"):
            raise ValueError("min_stable_scenario_fraction must be in [0, 1]")
        if self.max_net_edge_degradation_percent < 0:
            raise ValueError("max_net_edge_degradation_percent must be non-negative")


@dataclass(frozen=True)
class CostScenarioResult:
    scenario_id: str
    total_cost_percent: Decimal
    net_edge_percent: Decimal
    net_edge_degradation_percent: Decimal
    retained_net_edge_fraction: Decimal
    fee_increase_percent: Decimal
    funding_increase_percent: Decimal
    slippage_increase_percent: Decimal
    market_impact_increase_percent: Decimal
    passed: bool


@dataclass(frozen=True)
class CostRobustnessReport:
    gross_edge_percent: Decimal
    baseline_total_cost_percent: Decimal
    baseline_net_edge_percent: Decimal
    scenario_results: tuple[CostScenarioResult, ...]
    stable_scenario_fraction: Decimal
    worst_net_edge_percent: Decimal
    worst_net_edge_degradation_percent: Decimal
    passed: bool
    evidence_fingerprint: str


def assumption_from_backtest_model(
    model: BacktestCostModel,
    *,
    direction: str,
    held_minutes: int,
    market_impact_percent: Decimal = Decimal("0"),
    scenario_id: str = "BASELINE",
) -> CostAssumption:
    if held_minutes < 0:
        raise ValueError("held_minutes must be non-negative")
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Unsupported direction: {direction}")
    funding = (
        model.funding_rate_percent_per_day
        * Decimal(held_minutes)
        / Decimal("1440")
    )
    if direction == "SHORT":
        funding = -funding
    return CostAssumption(
        scenario_id=scenario_id,
        fee_percent=model.commission_percent * Decimal("2"),
        funding_percent=funding,
        slippage_percent=model.slippage_percent * Decimal("2"),
        market_impact_percent=market_impact_percent,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _require_adverse_or_equal(
    baseline: CostAssumption,
    scenario: CostAssumption,
) -> None:
    comparisons = (
        ("fee_percent", scenario.fee_percent, baseline.fee_percent),
        ("funding_percent", scenario.funding_percent, baseline.funding_percent),
        ("slippage_percent", scenario.slippage_percent, baseline.slippage_percent),
        (
            "market_impact_percent",
            scenario.market_impact_percent,
            baseline.market_impact_percent,
        ),
    )
    for name, stressed, base in comparisons:
        if stressed < base:
            raise ValueError(
                f"stress scenario {scenario.scenario_id!r} improves {name}; "
                "cost stress must be adverse or equal"
            )


def _fingerprint(
    *,
    gross_edge_percent: Decimal,
    baseline: CostAssumption,
    thresholds: CostRobustnessThresholds,
    scenario_results: tuple[CostScenarioResult, ...],
    stable_scenario_fraction: Decimal,
    worst_net_edge_percent: Decimal,
    worst_net_edge_degradation_percent: Decimal,
    passed: bool,
) -> str:
    payload = {
        "gross_edge_percent": _decimal_text(gross_edge_percent),
        "baseline": {
            "scenario_id": baseline.scenario_id,
            "fee_percent": _decimal_text(baseline.fee_percent),
            "funding_percent": _decimal_text(baseline.funding_percent),
            "slippage_percent": _decimal_text(baseline.slippage_percent),
            "market_impact_percent": _decimal_text(
                baseline.market_impact_percent
            ),
            "total_cost_percent": _decimal_text(baseline.total_cost_percent),
        },
        "thresholds": {
            "min_scenario_count": thresholds.min_scenario_count,
            "min_stable_scenario_fraction": _decimal_text(
                thresholds.min_stable_scenario_fraction
            ),
            "max_net_edge_degradation_percent": _decimal_text(
                thresholds.max_net_edge_degradation_percent
            ),
            "min_net_edge_percent": _decimal_text(thresholds.min_net_edge_percent),
            "max_scenarios": thresholds.max_scenarios,
        },
        "stable_scenario_fraction": _decimal_text(stable_scenario_fraction),
        "worst_net_edge_percent": _decimal_text(worst_net_edge_percent),
        "worst_net_edge_degradation_percent": _decimal_text(
            worst_net_edge_degradation_percent
        ),
        "passed": passed,
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "total_cost_percent": _decimal_text(item.total_cost_percent),
                "net_edge_percent": _decimal_text(item.net_edge_percent),
                "net_edge_degradation_percent": _decimal_text(
                    item.net_edge_degradation_percent
                ),
                "retained_net_edge_fraction": _decimal_text(
                    item.retained_net_edge_fraction
                ),
                "fee_increase_percent": _decimal_text(item.fee_increase_percent),
                "funding_increase_percent": _decimal_text(
                    item.funding_increase_percent
                ),
                "slippage_increase_percent": _decimal_text(
                    item.slippage_increase_percent
                ),
                "market_impact_increase_percent": _decimal_text(
                    item.market_impact_increase_percent
                ),
                "passed": item.passed,
            }
            for item in scenario_results
        ],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def qualify_cost_robustness(
    gross_edge_percent: Decimal,
    baseline: CostAssumption,
    stress_scenarios: tuple[CostAssumption, ...],
    *,
    thresholds: CostRobustnessThresholds = CostRobustnessThresholds(),
) -> CostRobustnessReport:
    if not gross_edge_percent.is_finite():
        raise ValueError("gross_edge_percent must be finite")
    if gross_edge_percent <= 0:
        raise ValueError("gross_edge_percent must be positive")
    if len(stress_scenarios) < thresholds.min_scenario_count:
        raise ValueError("insufficient cost stress scenarios")
    if len(stress_scenarios) > thresholds.max_scenarios:
        raise ValueError("cost stress scenario count exceeds max_scenarios")

    ids = [scenario.scenario_id for scenario in stress_scenarios]
    if len(set(ids)) != len(ids):
        raise ValueError("stress scenario_id values must be unique")
    if baseline.scenario_id in set(ids):
        raise ValueError("baseline scenario_id must not be reused by stress scenarios")

    baseline_net = gross_edge_percent - baseline.total_cost_percent
    if baseline_net <= 0:
        raise ValueError("baseline net edge must be positive")

    ordered = tuple(sorted(stress_scenarios, key=lambda item: item.scenario_id))
    results: list[CostScenarioResult] = []
    hundred = Decimal("100")
    for scenario in ordered:
        _require_adverse_or_equal(baseline, scenario)
        net_edge = gross_edge_percent - scenario.total_cost_percent
        degradation = max(
            Decimal("0"),
            (baseline_net - net_edge) / baseline_net * hundred,
        )
        retained = net_edge / baseline_net
        scenario_passed = (
            net_edge >= thresholds.min_net_edge_percent
            and degradation <= thresholds.max_net_edge_degradation_percent
        )
        results.append(
            CostScenarioResult(
                scenario_id=scenario.scenario_id,
                total_cost_percent=scenario.total_cost_percent,
                net_edge_percent=net_edge,
                net_edge_degradation_percent=degradation,
                retained_net_edge_fraction=retained,
                fee_increase_percent=scenario.fee_percent - baseline.fee_percent,
                funding_increase_percent=(
                    scenario.funding_percent - baseline.funding_percent
                ),
                slippage_increase_percent=(
                    scenario.slippage_percent - baseline.slippage_percent
                ),
                market_impact_increase_percent=(
                    scenario.market_impact_percent
                    - baseline.market_impact_percent
                ),
                passed=scenario_passed,
            )
        )

    scenario_results = tuple(results)
    stable_count = sum(item.passed for item in scenario_results)
    stable_fraction = Decimal(stable_count) / Decimal(len(scenario_results))
    worst_net_edge = min(item.net_edge_percent for item in scenario_results)
    worst_degradation = max(
        item.net_edge_degradation_percent for item in scenario_results
    )
    passed = stable_fraction >= thresholds.min_stable_scenario_fraction
    fingerprint = _fingerprint(
        gross_edge_percent=gross_edge_percent,
        baseline=baseline,
        thresholds=thresholds,
        scenario_results=scenario_results,
        stable_scenario_fraction=stable_fraction,
        worst_net_edge_percent=worst_net_edge,
        worst_net_edge_degradation_percent=worst_degradation,
        passed=passed,
    )
    return CostRobustnessReport(
        gross_edge_percent=gross_edge_percent,
        baseline_total_cost_percent=baseline.total_cost_percent,
        baseline_net_edge_percent=baseline_net,
        scenario_results=scenario_results,
        stable_scenario_fraction=stable_fraction,
        worst_net_edge_percent=worst_net_edge,
        worst_net_edge_degradation_percent=worst_degradation,
        passed=passed,
        evidence_fingerprint=fingerprint,
    )
