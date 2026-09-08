from decimal import Decimal

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position
from app.core.position_monitor import calculate_realized_pnl, monitor_open_positions, stop_was_crossed


def make_position(side: PositionSide) -> Position:
    return Position(
        position_id="P-001",
        symbol="BTC/USDT",
        side=side,
        entry_price=Decimal("100"),
        stop_loss=Decimal("90") if side is PositionSide.LONG else Decimal("110"),
        total_amount=Decimal("100"),
        quantity=Decimal("1"),
        leverage=Decimal("2"),
    )


def test_long_stop_is_crossed_at_or_below_sl() -> None:
    position = make_position(PositionSide.LONG)
    assert stop_was_crossed(position, Decimal("90"))
    assert stop_was_crossed(position, Decimal("89"))
    assert not stop_was_crossed(position, Decimal("90.01"))


def test_short_stop_is_crossed_at_or_above_sl() -> None:
    position = make_position(PositionSide.SHORT)
    assert stop_was_crossed(position, Decimal("110"))
    assert stop_was_crossed(position, Decimal("111"))
    assert not stop_was_crossed(position, Decimal("109.99"))


def test_pnl_is_relative_to_total_amount_and_leverage() -> None:
    position = make_position(PositionSide.LONG)
    pnl = calculate_realized_pnl(position, Decimal("90"))
    assert pnl == Decimal("-20")


def test_monitor_closes_crossed_position_and_records_pnl() -> None:
    position = make_position(PositionSide.LONG)
    summary = monitor_open_positions([position], lambda _: Decimal("89"))

    assert summary.monitored == 1
    assert summary.stopped_out == 1
    assert position.status is PositionStatus.STOPPED_OUT
    assert position.exit_price == Decimal("89")
    assert position.realized_pnl == Decimal("-22")
    assert position.close_reason == "STOP_LOSS"
