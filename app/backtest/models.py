from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class BacktestConfig:
    initial_equity: Decimal = Decimal("10000")
    risk_per_trade_percent: Decimal = Decimal("1")
    max_aggregate_risk_percent: Decimal = Decimal("4")
    max_futures_capital_percent: Decimal = Decimal("50")
    commission_percent: Decimal = Decimal("0")
    slippage_percent: Decimal = Decimal("0")
    spread_percent: Decimal = Decimal("0")
    funding_rate_percent_per_day: Decimal = Decimal("0")
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        for name in (
            "risk_per_trade_percent",
            "max_aggregate_risk_percent",
            "max_futures_capital_percent",
            "commission_percent",
            "slippage_percent",
            "spread_percent",
        ):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.risk_per_trade_percent > self.max_aggregate_risk_percent:
            raise ValueError("risk_per_trade_percent cannot exceed max_aggregate_risk_percent")


@dataclass(frozen=True)
class TradeRecord:
    position_id: str
    symbol: str
    direction: str
    setup: str
    entry_time: datetime
    entry_price: Decimal
    exit_time: datetime
    exit_price: Decimal
    stop_loss: Decimal
    target: Decimal
    quantity: Decimal
    total_amount: Decimal
    leverage: Decimal
    realized_pnl: Decimal
    commission: Decimal
    exit_reason: str
    funding_cost: Decimal = Decimal("0")


@dataclass(frozen=True)
class BacktestResult:
    initial_equity: Decimal
    final_equity: Decimal
    trades: tuple[TradeRecord, ...]
    rejected_signals: int
    open_positions_at_end: int
    max_drawdown_percent: Decimal
    win_rate_percent: Decimal
    profit_factor: Optional[Decimal]
    total_return_percent: Decimal
    max_concurrent_positions: int
