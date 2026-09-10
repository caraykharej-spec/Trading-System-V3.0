"""Scheduler core for deployment runtime.

Provides lightweight task registration and periodic execution foundation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict


@dataclass
class ScheduledTask:
    name: str
    interval_seconds: int
    callback: Callable | None = None
    enabled: bool = True


@dataclass
class SchedulerState:
    status: str = "STOPPED"
    started_at: datetime | None = None


class Scheduler:
    def __init__(self):
        self.tasks: Dict[str, ScheduledTask] = {}
        self.state = SchedulerState()

    def register_task(self, task: ScheduledTask):
        self.tasks[task.name] = task

    def start(self):
        self.state.status = "RUNNING"
        self.state.started_at = datetime.utcnow()

    def stop(self):
        self.state.status = "STOPPED"

    def run_task(self, name: str):
        task = self.tasks.get(name)
        if task and task.enabled and task.callback:
            return task.callback()
        return None
