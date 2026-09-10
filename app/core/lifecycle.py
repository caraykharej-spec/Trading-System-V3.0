"""Trading system lifecycle management."""

from .state import RuntimeState


class LifecycleManager:
    def __init__(self):
        self.state = RuntimeState.CREATED

    def transition(self, state: RuntimeState):
        self.state = state
        return self.state

    def current(self):
        return self.state
