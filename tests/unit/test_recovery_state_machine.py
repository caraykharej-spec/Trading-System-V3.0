from __future__ import annotations

import pytest

from app.recovery.models import RecoveryState
from app.recovery.state_machine import RecoveryStateMachine


def test_recovery_state_machine_reaches_ready() -> None:
    machine = RecoveryStateMachine()

    machine.transition(RecoveryState.LOADING_STATE)
    machine.transition(RecoveryState.VALIDATING)
    machine.transition(RecoveryState.RECONCILING)
    machine.transition(RecoveryState.READY)

    assert machine.state is RecoveryState.READY


def test_recovery_state_machine_rejects_invalid_transition() -> None:
    machine = RecoveryStateMachine()

    with pytest.raises(ValueError):
        machine.transition(RecoveryState.READY)
