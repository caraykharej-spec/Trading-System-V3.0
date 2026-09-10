"""Trading readiness gate for system health validation."""
from dataclasses import dataclass


@dataclass
class TradingReadiness:
    ready: bool
    reason: str


class TradingReadinessGate:
    def evaluate(self, health_passed: bool) -> TradingReadiness:
        if health_passed:
            return TradingReadiness(True, "System health validation passed")
        return TradingReadiness(False, "System health validation failed")
