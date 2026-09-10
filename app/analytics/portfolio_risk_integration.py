"""Portfolio risk integration for analytics layer."""

from dataclasses import dataclass


@dataclass
class PortfolioRiskSnapshot:
    equity: float
    exposure: float
    margin_usage: float
    drawdown: float
    risk_state: str


class PortfolioRiskIntegration:
    """Adapter between portfolio state and risk analytics view."""

    def create_snapshot(self, portfolio_state: dict) -> PortfolioRiskSnapshot:
        equity = float(portfolio_state.get("equity", 0.0))
        exposure = float(portfolio_state.get("exposure", 0.0))
        margin_usage = float(portfolio_state.get("margin_usage", 0.0))
        drawdown = float(portfolio_state.get("drawdown", 0.0))

        risk_state = "NORMAL"
        if drawdown > 0.2 or margin_usage > 0.8:
            risk_state = "HIGH"
        elif drawdown > 0.1 or margin_usage > 0.5:
            risk_state = "WARNING"

        return PortfolioRiskSnapshot(
            equity=equity,
            exposure=exposure,
            margin_usage=margin_usage,
            drawdown=drawdown,
            risk_state=risk_state,
        )
