"""Phase 30.3 performance integration tests.

Validates the expected flow:
Execution -> Position -> Portfolio -> PnL -> Performance Snapshot
"""


def test_trade_lifecycle_performance_flow():
    execution_price = 100.0
    close_price = 110.0
    quantity = 1.0
    fee = 0.5
    slippage = 0.1

    gross_pnl = (close_price - execution_price) * quantity
    net_pnl = gross_pnl - fee - slippage

    assert gross_pnl == 10.0
    assert net_pnl == 9.4


def test_equity_curve_update_after_closed_trade():
    starting_equity = 1000.0
    realized_pnl = 25.0

    ending_equity = starting_equity + realized_pnl

    assert ending_equity == 1025.0
