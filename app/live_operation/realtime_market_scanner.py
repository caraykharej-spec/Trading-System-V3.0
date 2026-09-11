from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ScanBatch(Generic[T]):
    items: tuple[T, ...]
    scanned_at: datetime
    source: str


class RealTimeMarketScanner(Generic[T]):
    """Runtime wrapper around the existing scanner/opportunity engine.

    The production layer controls cadence and observability while the existing
    scanner remains responsible for market-selection logic.
    """

    def __init__(self, scan: Callable[[], list[T]], source: str = "production") -> None:
        self._scan = scan
        self.source = source

    def run_once(self) -> ScanBatch[T]:
        return ScanBatch(
            items=tuple(self._scan()),
            scanned_at=datetime.now(timezone.utc),
            source=self.source,
        )
