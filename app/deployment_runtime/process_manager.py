"""Process Manager Layer

Provides service lifecycle control for the deployment runtime layer.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProcessState:
    name: str
    status: str = "STOPPED"
    updated_at: datetime = field(default_factory=datetime.utcnow)


class ProcessManager:
    def __init__(self):
        self.processes = {}

    def register(self, name: str):
        self.processes[name] = ProcessState(name=name)
        return self.processes[name]

    def start(self, name: str):
        process = self.processes[name]
        process.status = "RUNNING"
        process.updated_at = datetime.utcnow()
        return process

    def stop(self, name: str):
        process = self.processes[name]
        process.status = "STOPPED"
        process.updated_at = datetime.utcnow()
        return process

    def restart(self, name: str):
        self.stop(name)
        return self.start(name)
