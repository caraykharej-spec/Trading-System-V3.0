from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.execution.models import OrderRequest, OrderResult


@dataclass(frozen=True)
class ConnectorStatus:
    venue: str
    connected: bool
    authenticated: bool
    trading_enabled: bool
    reason: str = ""

    @property
    def ready(self) -> bool:
        return self.connected and self.authenticated and self.trading_enabled


@dataclass(frozen=True)
class VenuePosition:
    symbol: str
    quantity: Decimal
    entry_price: Decimal
    side: str


class ExchangeProductionConnector(ABC):
    """Production connector boundary.

    Implementations own venue-specific transport/authentication. The live
    operation layer depends only on this contract and never on vendor SDKs.
    """

    @abstractmethod
    def status(self) -> ConnectorStatus:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def open_positions(self) -> list[VenuePosition]:
        raise NotImplementedError


class DisabledProductionConnector(ExchangeProductionConnector):
    """Safe default used until a real connector is configured."""

    def __init__(self, venue: str = "UNCONFIGURED") -> None:
        self.venue = venue

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(
            venue=self.venue,
            connected=False,
            authenticated=False,
            trading_enabled=False,
            reason="production connector is disabled",
        )

    def submit_order(self, order: OrderRequest) -> OrderResult:
        raise RuntimeError("production connector is disabled")

    def open_positions(self) -> list[VenuePosition]:
        return []
