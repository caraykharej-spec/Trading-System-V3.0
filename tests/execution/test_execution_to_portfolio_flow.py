from app.portfolio.portfolio_state import PortfolioState


def test_execution_updates_portfolio_state():
    portfolio = PortfolioState(cash_balance=1000, equity=1000)
    portfolio.update_position("BTC", 0.5)

    assert portfolio.positions["BTC"] == 0.5
