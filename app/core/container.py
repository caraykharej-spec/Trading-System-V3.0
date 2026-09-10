"""Dependency container for Trading System runtime wiring."""


class TradingContainer:
    """Central registry for system services and engines."""

    def __init__(self):
        self.data_engine = None
        self.scanner_engine = None
        self.strategy_engine = None
        self.score_engine = None
        self.risk_engine = None
        self.portfolio_engine = None
        self.journal_engine = None

    def register(self, name: str, component):
        setattr(self, name, component)

    def get(self, name: str):
        return getattr(self, name, None)
