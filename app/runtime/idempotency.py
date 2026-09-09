from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    result_id: str


class OperationRepository(Protocol):
    def get(self, operation_id: str) -> OperationRecord | None: ...
    def save(self, record: OperationRecord) -> None: ...


class InMemoryOperationRepository:
    def __init__(self) -> None:
        self._records: dict[str, OperationRecord] = {}

    def get(self, operation_id: str) -> OperationRecord | None:
        return self._records.get(operation_id)

    def save(self, record: OperationRecord) -> None:
        existing = self._records.get(record.operation_id)
        if existing is not None and existing.result_id != record.result_id:
            raise ValueError("operation_id already has a different result")
        self._records[record.operation_id] = record


class IdempotencyGuard:
    """Prevents a retried runtime operation from producing a second result."""

    def __init__(self, repository: OperationRepository) -> None:
        self.repository = repository

    def existing_result(self, operation_id: str) -> str | None:
        record = self.repository.get(operation_id)
        return record.result_id if record else None

    def record(self, operation_id: str, result_id: str) -> None:
        self.repository.save(OperationRecord(operation_id, result_id))
