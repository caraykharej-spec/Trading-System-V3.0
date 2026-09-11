"""Trading system lifecycle management."""

from .state import RuntimeState


class LifecycleManager:
    def __init__(self) -> None:
        self.state = RuntimeState.CREATED

    def transition(self, state: RuntimeState) -> RuntimeState:
        self.state = state
        return self.state

    def current(self) -> RuntimeState:
        return self.state
