"""Risk adjusted performance metric foundation."""

import math


class RiskMetrics:
    def sharpe_ratio(self, returns, risk_free_rate=0.0):
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((x - mean) ** 2 for x in returns) / len(returns)
        deviation = math.sqrt(variance)
        return 0.0 if deviation == 0 else (mean - risk_free_rate) / deviation

    def sortino_ratio(self, returns, target=0.0):
        if not returns:
            return 0.0
        mean = sum(returns) / len(returns)
        downside = [x for x in returns if x < target]
        if not downside:
            return 0.0
        deviation = math.sqrt(sum((x - target) ** 2 for x in downside) / len(downside))
        return 0.0 if deviation == 0 else mean / deviation
