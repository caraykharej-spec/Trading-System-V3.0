from app.portfolio.balance_manager import BalanceManager
from app.portfolio.equity_tracker import EquityTracker


def test_available_balance():
    manager = BalanceManager(balance=1000, locked_margin=200)
    assert manager.available_balance == 800


def test_equity():
    tracker = EquityTracker(balance=1000, unrealized_pnl=50)
    assert tracker.equity == 1050
