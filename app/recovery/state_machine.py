from __future__ import annotations

from app.recovery.models import RecoveryState


_ALLOWED: dict[RecoveryState, set[RecoveryState]] = {
    RecoveryState.STARTING: {RecoveryState.LOADING_STATE, RecoveryState.HALTED},
    RecoveryState.LOADING_STATE: {RecoveryState.VALIDATING, RecoveryState.HALTED},
    RecoveryState.VALIDATING: {RecoveryState.RECONCILING, RecoveryState.READY, RecoveryState.HALTED},
    RecoveryState.RECONCILING: {RecoveryState.READY, RecoveryState.DEGRADED, RecoveryState.HALTED},
    RecoveryState.DEGRADED: {RecoveryState.READY, RecoveryState.HALTED},
    RecoveryState.READY: set(),
    RecoveryState.HALTED: set(),
}


class RecoveryStateMachine:
    def __init__(self) -> None:
        self.state = RecoveryState.STARTING

    def transition(self, target: RecoveryState) -> None:
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"invalid recovery transition: {self.state}->{target}")
        self.state = target
