from dataclasses import dataclass


@dataclass
class PortfolioSnapshot:
    equity: float
    cash_balance: float
    used_margin: float
    available_balance: float


@dataclass
class BalanceSnapshot:
    total: float
    available: float
    locked: float
