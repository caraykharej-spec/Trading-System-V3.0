from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from .exchange_connector import ExchangeProductionConnector, VenuePosition


@dataclass(frozen=True)
class LocalPositionSnapshot:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    side: str


@dataclass(frozen=True)
class PositionMismatch:
    symbol: str
    field: str
    local_value: str
    venue_value: str


@dataclass(frozen=True)
class PositionSyncReport:
    synchronized: bool
    mismatches: tuple[PositionMismatch, ...]


class LivePositionSynchronizer:
    """Compares venue positions with local state without silently mutating either side."""

    def __init__(
        self,
        connector: ExchangeProductionConnector,
        local_positions: Callable[[], Iterable[LocalPositionSnapshot]],
    ) -> None:
        self.connector = connector
        self._local_positions = local_positions

    @staticmethod
    def _key(position: LocalPositionSnapshot | VenuePosition) -> str:
        return position.symbol.upper()

    def reconcile(self) -> PositionSyncReport:
        local = {self._key(p): p for p in self._local_positions()}
        venue = {self._key(p): p for p in self.connector.open_positions()}
        mismatches: list[PositionMismatch] = []

        for symbol in sorted(set(local) | set(venue)):
            lp = local.get(symbol)
            vp = venue.get(symbol)
            if lp is None:
                mismatches.append(PositionMismatch(symbol, "presence", "missing", "present"))
                continue
            if vp is None:
                mismatches.append(PositionMismatch(symbol, "presence", "present", "missing"))
                continue
            for field in ("quantity", "entry_price", "side"):
                lv = getattr(lp, field)
                vv = getattr(vp, field)
                if str(lv) != str(vv):
                    mismatches.append(PositionMismatch(symbol, field, str(lv), str(vv)))

        return PositionSyncReport(
            synchronized=not mismatches,
            mismatches=tuple(mismatches),
        )
