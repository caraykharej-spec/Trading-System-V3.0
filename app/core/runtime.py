"""Main runtime orchestration layer."""

from .state import RuntimeState
from .lifecycle import LifecycleManager


class TradingRuntime:
    def __init__(self, container):
        self.container = container
        self.lifecycle = LifecycleManager()
        self.running = False

    def initialize(self):
        self.lifecycle.transition(RuntimeState.INITIALIZING)
        self.lifecycle.transition(RuntimeState.READY)

    def start_cycle(self):
        self.lifecycle.transition(RuntimeState.RUNNING)

        self.lifecycle.transition(RuntimeState.SCANNING)
        scanner = self.container.get("scanner_engine")

        if scanner:
            result = scanner.scan()
        else:
            result = []

        self.lifecycle.transition(RuntimeState.COMPLETED)
        return result

    def stop(self):
        self.running = False
        self.lifecycle.transition(RuntimeState.STOPPED)
