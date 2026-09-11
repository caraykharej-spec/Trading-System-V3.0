from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.analytics.performance import PerformanceReport, analyze_performance
from app.core.models import Position
from app.data.market_data import Candle
from app.journal.models import JournalEntry
from app.position.manager import calculate_realized_pnl


PositionsProvider = Callable[[], Sequence[Position]]
JournalProvider = Callable[[], Sequence[JournalEntry]]
LivePriceProvider = Callable[[str], Decimal]
CandlesProvider = Callable[[str, str, int], Sequence[Candle]]


@dataclass(frozen=True)
class PositionAnalyticsItem:
    position_id: str
    symbol: str
    side: str
    entry_price: Decimal
    current_price: Decimal | None
    stop_loss: Decimal
    take_profit: Decimal | None
    total_amount: Decimal
    quantity: Decimal
    leverage: Decimal
    unrealized_pnl: Decimal | None
    opened_at: datetime


@dataclass(frozen=True)
class PositionAnalyticsSnapshot:
    items: tuple[PositionAnalyticsItem, ...]
    total_unrealized_pnl: Decimal | None
    missing_live_prices: tuple[str, ...] = ()


@dataclass(frozen=True)
class JournalTradeView:
    position_id: str
    symbol: str
    side: str
    realized_pnl: Decimal
    return_percent: Decimal
    realized_r_multiple: Decimal | None
    close_reason: str
    closed_at: datetime


@dataclass(frozen=True)
class JournalAnalyticsSnapshot:
    report: PerformanceReport
    recent: tuple[JournalTradeView, ...]
    symbol: str | None = None


@dataclass(frozen=True)
class MarketChangePoint:
    timeframe: str
    reference_close: Decimal
    reference_timestamp: datetime
    current_price: Decimal
    change_percent: Decimal


@dataclass(frozen=True)
class MarketChangeSnapshot:
    symbol: str
    current_price: Decimal | None
    points: tuple[MarketChangePoint, ...]
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class WhatIfPositionImpact:
    position_id: str
    side: str
    current_unrealized_pnl: Decimal
    hypothetical_pnl: Decimal
    pnl_delta: Decimal


@dataclass(frozen=True)
class WhatIfSnapshot:
    symbol: str
    percent_change: Decimal
    current_price: Decimal | None
    hypothetical_price: Decimal | None
    impacts: tuple[WhatIfPositionImpact, ...]
    current_total_pnl: Decimal | None
    hypothetical_total_pnl: Decimal | None
    pnl_delta: Decimal | None
    missing: tuple[str, ...] = ()
    hypothetical: bool = True
    execution_authority: bool = False


class AssistantAnalyticsService:
    """Read-only analytics used by the grounded assistant.

    The service may read authoritative runtime state and market data but never mutates
    positions, journal entries, risk state, execution state, or venue state.
    """

    def __init__(
        self,
        *,
        positions_provider: PositionsProvider,
        journal_provider: JournalProvider,
        live_price_provider: LivePriceProvider,
        candles_provider: CandlesProvider,
        market_timeframes: tuple[str, ...] = ("15m", "1h", "4h", "1d"),
        recent_journal_limit: int = 5,
    ) -> None:
        if not market_timeframes:
            raise ValueError("market_timeframes must not be empty")
        if recent_journal_limit < 1:
            raise ValueError("recent_journal_limit must be positive")
        self._positions_provider = positions_provider
        self._journal_provider = journal_provider
        self._live_price_provider = live_price_provider
        self._candles_provider = candles_provider
        self._market_timeframes = market_timeframes
        self._recent_journal_limit = recent_journal_limit

    def _safe_live_price(self, symbol: str) -> Decimal | None:
        try:
            price = Decimal(str(self._live_price_provider(symbol)))
        except Exception:
            return None
        return price if price > 0 else None

    def positions(self, symbol: str | None = None) -> PositionAnalyticsSnapshot:
        target = symbol.upper() if symbol is not None else None
        rows = [
            item
            for item in self._positions_provider()
            if target is None or item.symbol.upper() == target
        ]
        items: list[PositionAnalyticsItem] = []
        missing: list[str] = []
        total = Decimal("0")
        all_priced = True
        for position in rows:
            current_price = self._safe_live_price(position.symbol)
            unrealized: Decimal | None = None
            if current_price is None:
                all_priced = False
                missing.append(position.symbol.upper())
            else:
                unrealized = calculate_realized_pnl(position, current_price)
                total += unrealized
            items.append(
                PositionAnalyticsItem(
                    position_id=position.position_id,
                    symbol=position.symbol,
                    side=position.side.value,
                    entry_price=position.entry_price,
                    current_price=current_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    total_amount=position.total_amount,
                    quantity=position.quantity,
                    leverage=position.leverage,
                    unrealized_pnl=unrealized,
                    opened_at=position.opened_at,
                )
            )
        return PositionAnalyticsSnapshot(
            items=tuple(items),
            total_unrealized_pnl=total if all_priced else None,
            missing_live_prices=tuple(sorted(set(missing))),
        )

    def journal(self, symbol: str | None = None) -> JournalAnalyticsSnapshot:
        target = symbol.upper() if symbol is not None else None
        rows = [
            item
            for item in self._journal_provider()
            if target is None or item.symbol.upper() == target
        ]
        rows.sort(key=lambda item: (item.closed_at, item.position_id), reverse=True)
        recent = tuple(
            JournalTradeView(
                position_id=item.position_id,
                symbol=item.symbol,
                side=item.side.value,
                realized_pnl=item.realized_pnl,
                return_percent=item.return_percent,
                realized_r_multiple=item.realized_r_multiple,
                close_reason=item.close_reason,
                closed_at=item.closed_at,
            )
            for item in rows[: self._recent_journal_limit]
        )
        return JournalAnalyticsSnapshot(
            report=analyze_performance(rows),
            recent=recent,
            symbol=target,
        )

    def market_change(self, symbol: str) -> MarketChangeSnapshot:
        target = symbol.upper()
        current = self._safe_live_price(target)
        if current is None:
            return MarketChangeSnapshot(
                symbol=target,
                current_price=None,
                points=(),
                missing=("live_price",),
            )
        points: list[MarketChangePoint] = []
        missing: list[str] = []
        for timeframe in self._market_timeframes:
            try:
                candles = sorted(
                    self._candles_provider(target, timeframe, 2),
                    key=lambda item: item.timestamp,
                )
            except Exception:
                missing.append(f"candles:{timeframe}")
                continue
            if len(candles) < 2:
                missing.append(f"candles:{timeframe}")
                continue
            reference = candles[-2]
            if reference.close <= 0:
                missing.append(f"reference_close:{timeframe}")
                continue
            change = (current - reference.close) / reference.close * Decimal("100")
            points.append(
                MarketChangePoint(
                    timeframe=timeframe,
                    reference_close=reference.close,
                    reference_timestamp=reference.timestamp,
                    current_price=current,
                    change_percent=change,
                )
            )
        return MarketChangeSnapshot(
            symbol=target,
            current_price=current,
            points=tuple(points),
            missing=tuple(missing),
        )

    def what_if(self, symbol: str, percent_change: Decimal) -> WhatIfSnapshot:
        if percent_change <= Decimal("-100") or percent_change > Decimal("1000"):
            raise ValueError("what-if percent must be greater than -100 and at most 1000")
        target = symbol.upper()
        current = self._safe_live_price(target)
        if current is None:
            return WhatIfSnapshot(
                symbol=target,
                percent_change=percent_change,
                current_price=None,
                hypothetical_price=None,
                impacts=(),
                current_total_pnl=None,
                hypothetical_total_pnl=None,
                pnl_delta=None,
                missing=("live_price",),
            )
        hypothetical_price = current * (
            Decimal("1") + percent_change / Decimal("100")
        )
        if hypothetical_price <= 0:
            raise ValueError("what-if scenario produced a non-positive price")
        positions = [
            item
            for item in self._positions_provider()
            if item.symbol.upper() == target
        ]
        impacts: list[WhatIfPositionImpact] = []
        current_total = Decimal("0")
        hypothetical_total = Decimal("0")
        for position in positions:
            current_pnl = calculate_realized_pnl(position, current)
            hypothetical_pnl = calculate_realized_pnl(position, hypothetical_price)
            current_total += current_pnl
            hypothetical_total += hypothetical_pnl
            impacts.append(
                WhatIfPositionImpact(
                    position_id=position.position_id,
                    side=position.side.value,
                    current_unrealized_pnl=current_pnl,
                    hypothetical_pnl=hypothetical_pnl,
                    pnl_delta=hypothetical_pnl - current_pnl,
                )
            )
        return WhatIfSnapshot(
            symbol=target,
            percent_change=percent_change,
            current_price=current,
            hypothetical_price=hypothetical_price,
            impacts=tuple(impacts),
            current_total_pnl=current_total,
            hypothetical_total_pnl=hypothetical_total,
            pnl_delta=hypothetical_total - current_total,
        )
