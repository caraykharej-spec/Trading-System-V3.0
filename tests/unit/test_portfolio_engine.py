from decimal import Decimal

from app.core.enums import PositionSide
from app.core.models import Position
from app.portfolio.correlation import correlated_risk
from app.portfolio.portfolio_engine import PortfolioPolicy, assess_portfolio


def position(symbol: str, amount: str, entry: str = "100", stop: str = "90", leverage: str = "1") -> Position:
    return Position(symbol, symbol, PositionSide.LONG, Decimal(entry), Decimal(stop), Decimal(amount), Decimal(amount) / Decimal(entry), Decimal(leverage))


def test_aggregate_risk_respects_four_percent_limit() -> None:
    result = assess_portfolio(equity=Decimal("10000"), positions=[position("BTC", "3000")], new_risk=Decimal("100"), new_notional=Decimal("1000"))
    assert result.approved
    assert result.aggregate_risk_percent == Decimal("4")


def test_correlated_risk_can_block() -> None:
    result = assess_portfolio(equity=Decimal("10000"), positions=[position("BTC", "1000")], new_risk=Decimal("100"), new_notional=Decimal("1000"), correlation=Decimal("1"), policy=PortfolioPolicy(max_correlated_risk_percent=Decimal("1.5")))
    assert not result.approved
    assert "correlated risk exceeds portfolio limit" in result.reasons


def test_negative_correlation_does_not_create_negative_risk() -> None:
    assert correlated_risk(Decimal("100"), Decimal("500"), Decimal("-1")) == Decimal("100")


def test_futures_capital_respects_fifty_percent_limit() -> None:
    result = assess_portfolio(
        equity=Decimal("10000"),
        positions=[position("BTC", "4900", leverage="2")],
        new_risk=Decimal("100"),
        new_notional=Decimal("200"),
        new_futures_capital=Decimal("200"),
    )
    assert not result.approved
    assert result.futures_capital_percent == Decimal("53")
    assert "futures capital exceeds portfolio limit" in result.reasons
