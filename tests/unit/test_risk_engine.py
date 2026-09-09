from decimal import Decimal

from app.core.enums import PositionSide
from app.core.models import Position
from app.portfolio.account import Account
from app.risk.position_sizing import calculate_position_size
from app.risk.risk_engine import assess_risk
from app.risk.storm import storm_sl_loss_percent
from app.strategy.strategy_engine import StrategySignal, StrategyState
from app.strategy.scoring.confidence import ConfidenceResult
from app.strategy.scoring.score import ScoreBreakdown
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument


def signal() -> StrategySignal:
    breakdown = ScoreBreakdown(20, 15, 25, 15, 10, 5, 10)
    confidence = ConfidenceResult(95, ("DATA", "HTF"))
    return StrategySignal("BTC/USDT", "LONG", "CONTINUATION", StrategyState.READY_FOR_RISK_REVIEW, Decimal("100"), Decimal("99"), Decimal("102.5"), Decimal("2.5"), Decimal("100"), Decimal("95"), breakdown, confidence, ())


def contract() -> ContractSpec:
    return ContractSpec("BTC/USDT", Decimal("0.01"), Decimal("0.01"), Decimal("0.01"), max_leverage=10)


def instrument() -> Instrument:
    return Instrument("BTC/USDT", AssetClass.CRYPTO, "BTC", "USDT")


def test_storm_loss_is_price_distance_times_leverage() -> None:
    assert storm_sl_loss_percent(entry=Decimal("100"), stop_loss=Decimal("98"), leverage=Decimal("5")) == Decimal("10")


def test_position_size_respects_one_percent_equity_risk() -> None:
    quantity, amount = calculate_position_size(equity=Decimal("10000"), entry=Decimal("100"), stop_loss=Decimal("99"), leverage=Decimal("1"), risk_percent=Decimal("1"), contract=contract())
    assert quantity == Decimal("1.00")
    assert amount == Decimal("100.00")


def test_risk_engine_allows_within_budget() -> None:
    result = assess_risk(account=Account(Decimal("10000")), positions=[], signal=signal(), instrument=instrument(), contract=contract(), leverage=Decimal("1"))
    assert result.approved
    assert result.risk_percent <= Decimal("1")
    assert result.aggregate_risk <= Decimal("400")


def test_aggregate_risk_blocks_new_trade() -> None:
    existing = Position("P1", "ETH/USDT", PositionSide.LONG, Decimal("100"), Decimal("90"), Decimal("400"), Decimal("4"), Decimal("1"))
    result = assess_risk(account=Account(Decimal("10000")), positions=[existing], signal=signal(), instrument=instrument(), contract=contract(), leverage=Decimal("1"))
    assert not result.approved
    assert "aggregate open risk exceeds portfolio limit" in result.reasons
