"""Main runtime orchestration layer."""

from typing import Any, cast

from .container import TradingContainer
from .lifecycle import LifecycleManager
from .state import RuntimeState


class TradingRuntime:
    def __init__(self, container: TradingContainer) -> None:
        self.container = container
        self.lifecycle = LifecycleManager()
        self.running = False

    def initialize(self) -> None:
        self.lifecycle.transition(RuntimeState.INITIALIZING)
        self.lifecycle.transition(RuntimeState.READY)

    def start_cycle(self) -> list[Any]:
        self.lifecycle.transition(RuntimeState.RUNNING)

        self.lifecycle.transition(RuntimeState.SCANNING)
        scanner = self.container.get("scanner_engine")

        if scanner is not None:
            result = cast(list[Any], scanner.scan())
        else:
            result = []

        self.lifecycle.transition(RuntimeState.COMPLETED)
        return result

    def stop(self) -> None:
        self.running = False
        self.lifecycle.transition(RuntimeState.STOPPED)
