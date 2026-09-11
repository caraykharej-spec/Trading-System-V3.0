"""Dependency container for Trading System runtime wiring."""

from typing import Any


class TradingContainer:
    """Central registry for system services and engines."""

    def __init__(self) -> None:
        self.data_engine: Any | None = None
        self.scanner_engine: Any | None = None
        self.strategy_engine: Any | None = None
        self.score_engine: Any | None = None
        self.risk_engine: Any | None = None
        self.portfolio_engine: Any | None = None
        self.journal_engine: Any | None = None

    def register(self, name: str, component: Any) -> None:
        setattr(self, name, component)

    def get(self, name: str) -> Any | None:
        return getattr(self, name, None)
