from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.performance import analyze_performance
from app.analytics.service import AnalyticsService
from app.core.enums import PositionSide
from app.journal.in_memory_repository import InMemoryJournalRepository
from app.journal.models import JournalEntry


def entry(position_id: str, pnl: str, minute: int, symbol: str = "BTC/USDT") -> JournalEntry:
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return JournalEntry(
        position_id=position_id,
        symbol=symbol,
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        total_amount=Decimal("1000"),
        quantity=Decimal("10"),
        leverage=Decimal("1"),
        realized_pnl=Decimal(pnl),
        opened_at=opened,
        closed_at=opened + timedelta(minutes=minute),
        close_reason="TEST",
    )


def test_performance_report_calculates_realized_metrics() -> None:
    rows = [
        entry("P-1", "100", 1),
        entry("P-2", "-50", 2),
        entry("P-3", "-25", 3),
        entry("P-4", "0", 4),
        entry("P-5", "200", 5),
    ]
    report = analyze_performance(rows)

    assert report.total_trades == 5
    assert (report.wins, report.losses, report.breakeven) == (2, 2, 1)
    assert report.gross_profit == Decimal("300")
    assert report.gross_loss == Decimal("75")
    assert report.net_pnl == Decimal("225")
    assert report.win_rate_percent == Decimal("40")
    assert report.average_pnl == Decimal("45")
    assert report.average_win == Decimal("150")
    assert report.average_loss == Decimal("-37.5")
    assert report.profit_factor == Decimal("4")
    assert report.expectancy == Decimal("45.0")
    assert report.max_consecutive_losses == 2
    assert report.best_trade == Decimal("200")
    assert report.worst_trade == Decimal("-50")


def test_empty_performance_report_is_well_defined() -> None:
    report = analyze_performance([])
    assert report.total_trades == 0
    assert report.net_pnl == Decimal("0")
    assert report.win_rate_percent == Decimal("0")
    assert report.profit_factor is None
    assert report.best_trade is None
    assert report.worst_trade is None


def test_analytics_service_can_filter_by_symbol() -> None:
    repository = InMemoryJournalRepository(
        [
            entry("P-1", "100", 1, "BTC/USDT"),
            entry("P-2", "-50", 2, "BTC/USDT"),
            entry("P-3", "200", 3, "ETH/USDT"),
        ]
    )
    service = AnalyticsService(repository)

    assert service.performance().net_pnl == Decimal("250")
    assert service.performance("BTC/USDT").net_pnl == Decimal("50")
    assert service.performance("ETH/USDT").total_trades == 1
