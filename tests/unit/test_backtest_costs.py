from decimal import Decimal

import pytest

from app.backtest.costs import BacktestCostModel
from app.backtest.models import BacktestConfig


def test_spread_and_slippage_are_directionally_correct() -> None:
    model = BacktestCostModel(spread_percent=Decimal("1"), slippage_percent=Decimal("0.5"))
    assert model.entry_price("LONG", Decimal("100")) == Decimal("101")
    assert model.entry_price("SHORT", Decimal("100")) == Decimal("99")
    assert model.exit_price("LONG", Decimal("100")) == Decimal("99")
    assert model.exit_price("SHORT", Decimal("100")) == Decimal("101")


def test_funding_is_time_scaled_and_signed() -> None:
    model = BacktestCostModel(funding_rate_percent_per_day=Decimal("2"))
    assert model.funding("LONG", Decimal("1000"), 720) == Decimal("10")
    assert model.funding("SHORT", Decimal("1000"), 720) == Decimal("-10")


def test_negative_funding_is_allowed() -> None:
    model = BacktestCostModel(funding_rate_percent_per_day=Decimal("-1"))
    assert model.funding("LONG", Decimal("1000"), 1440) == Decimal("-10")


def test_cost_model_rejects_negative_execution_costs() -> None:
    with pytest.raises(ValueError):
        BacktestCostModel(spread_percent=Decimal("-0.1"))


def test_backtest_config_exposes_realism_parameters() -> None:
    config = BacktestConfig(spread_percent=Decimal("0.2"), funding_rate_percent_per_day=Decimal("0.01"))
    assert config.spread_percent == Decimal("0.2")
    assert config.funding_rate_percent_per_day == Decimal("0.01")
