from decimal import Decimal

import pytest

from app.backtest.cost_robustness import (
    CostAssumption,
    CostRobustnessThresholds,
    assumption_from_backtest_model,
    qualify_cost_robustness,
)
from app.backtest.costs import BacktestCostModel


def _cost(
    scenario_id: str,
    *,
    fee: str = "0.20",
    funding: str = "0.05",
    slippage: str = "0.10",
    impact: str = "0.05",
) -> CostAssumption:
    return CostAssumption(
        scenario_id=scenario_id,
        fee_percent=Decimal(fee),
        funding_percent=Decimal(funding),
        slippage_percent=Decimal(slippage),
        market_impact_percent=Decimal(impact),
    )


def _passing_stresses() -> tuple[CostAssumption, ...]:
    return (
        _cost("FEE", fee="0.35"),
        _cost("FUNDING", funding="0.20"),
        _cost("IMPACT", impact="0.25"),
        _cost("SLIPPAGE", slippage="0.30"),
    )


def test_cost_stress_passes_and_is_input_order_independent():
    baseline = _cost("BASELINE")
    first = qualify_cost_robustness(
        Decimal("2.0"), baseline, _passing_stresses()
    )
    second = qualify_cost_robustness(
        Decimal("2.0"), baseline, tuple(reversed(_passing_stresses()))
    )

    assert first.passed is True
    assert first == second
    assert first.baseline_total_cost_percent == Decimal("0.40")
    assert first.baseline_net_edge_percent == Decimal("1.60")
    assert first.stable_scenario_fraction == Decimal("1")
    assert len(first.evidence_fingerprint) == 64


def test_fee_stress_attribution_is_explicit():
    baseline = _cost("BASELINE")
    report = qualify_cost_robustness(
        Decimal("2.0"), baseline, _passing_stresses()
    )
    fee = next(item for item in report.scenario_results if item.scenario_id == "FEE")

    assert fee.fee_increase_percent == Decimal("0.15")
    assert fee.funding_increase_percent == Decimal("0")
    assert fee.slippage_increase_percent == Decimal("0")
    assert fee.market_impact_increase_percent == Decimal("0")


def test_severe_cost_stress_fails_closed():
    baseline = _cost("BASELINE")
    stresses = (*_passing_stresses()[:-1], _cost("SLIPPAGE", slippage="1.20"))
    report = qualify_cost_robustness(Decimal("2.0"), baseline, stresses)

    assert report.passed is False
    assert report.stable_scenario_fraction == Decimal("0.75")
    assert report.worst_net_edge_degradation_percent > Decimal("60")


def test_negative_funding_credit_can_be_stressed_toward_positive_cost():
    baseline = _cost("BASELINE", funding="-0.10")
    stresses = (
        _cost("FEE", funding="-0.10", fee="0.30"),
        _cost("FUNDING", funding="0.10"),
        _cost("IMPACT", funding="-0.10", impact="0.20"),
        _cost("SLIPPAGE", funding="-0.10", slippage="0.20"),
    )
    report = qualify_cost_robustness(Decimal("2.0"), baseline, stresses)

    funding = next(
        item for item in report.scenario_results if item.scenario_id == "FUNDING"
    )
    assert funding.funding_increase_percent == Decimal("0.20")
    assert report.passed is True


def test_backtest_model_adapter_preserves_existing_cost_contract():
    model = BacktestCostModel(
        commission_percent=Decimal("0.1"),
        slippage_percent=Decimal("0.05"),
        funding_rate_percent_per_day=Decimal("0.24"),
    )
    long = assumption_from_backtest_model(
        model,
        direction="LONG",
        held_minutes=720,
        market_impact_percent=Decimal("0.02"),
    )
    short = assumption_from_backtest_model(
        model,
        direction="SHORT",
        held_minutes=720,
        market_impact_percent=Decimal("0.02"),
        scenario_id="SHORT",
    )

    assert long.fee_percent == Decimal("0.2")
    assert long.slippage_percent == Decimal("0.10")
    assert long.funding_percent == Decimal("0.12")
    assert long.market_impact_percent == Decimal("0.02")
    assert short.funding_percent == Decimal("-0.12")


def test_stress_scenario_cannot_improve_any_cost_component():
    baseline = _cost("BASELINE")
    stresses = (
        _cost("BAD", fee="0.10"),
        _cost("FUNDING", funding="0.20"),
        _cost("IMPACT", impact="0.20"),
        _cost("SLIPPAGE", slippage="0.20"),
    )

    with pytest.raises(ValueError, match="must be adverse or equal"):
        qualify_cost_robustness(Decimal("2.0"), baseline, stresses)


def test_baseline_net_edge_must_be_positive():
    baseline = _cost(
        "BASELINE", fee="0.5", funding="0.5", slippage="0.5", impact="0.5"
    )
    with pytest.raises(ValueError, match="baseline net edge must be positive"):
        qualify_cost_robustness(Decimal("2.0"), baseline, _passing_stresses())


def test_duplicate_and_reused_scenario_ids_are_rejected():
    baseline = _cost("BASELINE")
    duplicate = (
        _cost("A"),
        _cost("A"),
        _cost("B"),
        _cost("C"),
    )
    with pytest.raises(ValueError, match="must be unique"):
        qualify_cost_robustness(Decimal("2.0"), baseline, duplicate)

    reused = (*_passing_stresses()[:-1], _cost("BASELINE", slippage="0.20"))
    with pytest.raises(ValueError, match="must not be reused"):
        qualify_cost_robustness(Decimal("2.0"), baseline, reused)


@pytest.mark.parametrize("value", ("NaN", "Infinity", "-Infinity"))
def test_non_finite_cost_assumptions_are_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        _cost("BAD", fee=value)


def test_execution_costs_must_be_non_negative():
    with pytest.raises(ValueError, match="fee_percent"):
        _cost("BAD", fee="-0.01")
    with pytest.raises(ValueError, match="slippage_percent"):
        _cost("BAD", slippage="-0.01")
    with pytest.raises(ValueError, match="market_impact_percent"):
        _cost("BAD", impact="-0.01")


def test_scenario_count_is_bounded():
    baseline = _cost("BASELINE")
    thresholds = CostRobustnessThresholds(min_scenario_count=1, max_scenarios=2)
    stresses = tuple(_cost(f"S{index}") for index in range(3))

    with pytest.raises(ValueError, match="max_scenarios"):
        qualify_cost_robustness(
            Decimal("2.0"), baseline, stresses, thresholds=thresholds
        )


def test_insufficient_scenarios_are_rejected():
    with pytest.raises(ValueError, match="insufficient cost stress"):
        qualify_cost_robustness(
            Decimal("2.0"), _cost("BASELINE"), _passing_stresses()[:3]
        )


def test_invalid_direction_and_holding_time_are_rejected():
    model = BacktestCostModel()
    with pytest.raises(ValueError, match="held_minutes"):
        assumption_from_backtest_model(model, direction="LONG", held_minutes=-1)
    with pytest.raises(ValueError, match="Unsupported direction"):
        assumption_from_backtest_model(model, direction="SIDEWAYS", held_minutes=1)
