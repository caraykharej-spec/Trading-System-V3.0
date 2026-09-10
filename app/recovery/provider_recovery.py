from __future__ import annotations

from enum import Enum


class ProviderRecoveryState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


class ProviderRecoveryPolicy:
    def allow_new_trades(self, state: ProviderRecoveryState, *, price_provider: bool) -> bool:
        if price_provider and state is not ProviderRecoveryState.AVAILABLE:
            return False
        return True
