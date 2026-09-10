"""Exchange adapter interfaces."""

from abc import ABC, abstractmethod

from .execution_models import ExecutionRequest, ExecutionResult


class ExecutionAdapter(ABC):
    """Base interface for exchange execution connectors."""

    @abstractmethod
    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError
