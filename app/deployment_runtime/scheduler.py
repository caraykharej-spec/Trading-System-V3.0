"""Scheduler core for deployment runtime.

Provides lightweight task registration and periodic execution foundation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ScheduledTask:
    name: str
    interval_seconds: int
    callback: Callable[[], object] | None = None
    enabled: bool = True


@dataclass
class SchedulerState:
    status: str = "STOPPED"
    started_at: datetime | None = None


class Scheduler:
    def __init__(self) -> None:
        self.tasks: dict[str, ScheduledTask] = {}
        self.state = SchedulerState()

    def register_task(self, task: ScheduledTask) -> None:
        self.tasks[task.name] = task

    def start(self) -> None:
        self.state.status = "RUNNING"
        self.state.started_at = datetime.utcnow()

    def stop(self) -> None:
        self.state.status = "STOPPED"

    def run_task(self, name: str) -> object | None:
        task = self.tasks.get(name)
        if task and task.enabled and task.callback:
            return task.callback()
        return None
