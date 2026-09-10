from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.application.composition import build_paper_application
from app.core.enums import PositionSide, PositionStatus, SystemMode
from app.core.models import Position
from app.data.market_data import Candle
from app.data.providers.yahoo import YahooFinanceProvider
from app.data.quality import validate_candles
from app.execution.models import OrderRequest, OrderType
from app.execution.risk_reservation import reserve_pending_order_risk
from app.journal.models import JournalEntry
from app.journal.sqlite_repository import SQLiteJournalRepository
from app.market.analysis import MarketSnapshot
from app.market.indicators import IndicatorSnapshot, build_snapshot
from app.market.liquidity import LiquidityResult
from app.market.regime import RegimeResult
from app.market.structure import StructureResult
from app.market.trend import TrendResult
from app.portfolio.account import Account
from app.portfolio.correlation import CorrelationMatrix, CorrelationPair
from app.position.settlement import PositionSettlementService
from app.storage.account_ledger import SQLiteAccountLedgerRepository
from app.storage.database import connect
from app.storage.repositories.sqlite_account_repository import SQLiteAccountRepository
from app.storage.repositories.sqlite_position_repository import SQLitePositionRepository
from app.strategy.evidence import build_strategy_evidence


UTC = timezone.utc


def _candle(index: int, *, timeframe: str = "1h", volume: str = "1000") -> Candle:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    base = Decimal("100") + Decimal(index) / Decimal("10")
    return Candle(
        symbol="TEST/USD",
        timeframe=timeframe,
        timestamp=timestamp,
        open=base - Decimal("0.2"),
        high=base + Decimal("0.8"),
        low=base - Decimal("0.7"),
        close=base,
        volume=Decimal(volume),
    )


def _indicator_snapshot(*, bullish: bool = True) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        ema20=Decimal("105") if bullish else Decimal("95"),
        ema50=Decimal("103") if bullish else Decimal("97"),
        ema200=Decimal("100"),
        rsi14=Decimal("60") if bullish else Decimal("40"),
        atr14=Decimal("2"),
        volume_sma20=Decimal("1000"),
        sma50=Decimal("103") if bullish else Decimal("97"),
        macd_line=Decimal("1") if bullish else Decimal("-1"),
        macd_signal=Decimal("0.5") if bullish else Decimal("-0.5"),
        macd_histogram=Decimal("0.5") if bullish else Decimal("-0.5"),
        adx14=Decimal("30"),
        supertrend_direction="BULLISH" if bullish else "BEARISH",
        vwap20=Decimal("104") if bullish else Decimal("96"),
        bollinger_middle=Decimal("103") if bullish else Decimal("97"),
        bollinger_upper=Decimal("108") if bullish else Decimal("102"),
        bollinger_lower=Decimal("98") if bullish else Decimal("92"),
    )


def _snapshot(
    timeframe: str,
    *,
    bullish: bool = True,
    trend_score: str = "95",
    structure_score: str = "95",
    liquidity_score: str = "95",
    volume_ratio: str = "1.5",
) -> MarketSnapshot:
    indicators = _indicator_snapshot(bullish=bullish)
    direction = "BULLISH" if bullish else "BEARISH"
    return MarketSnapshot(
        symbol="TEST/USD",
        timeframe=timeframe,
        indicators=indicators,
        trend=TrendResult(direction, "STRONG", Decimal(trend_score), indicators),
        structure=StructureResult(
            "BULLISH_STRUCTURE" if bullish else "BEARISH_STRUCTURE",
            Decimal("95"),
            Decimal("110"),
            Decimal(structure_score),
        ),
        regime=RegimeResult(
            "TRENDING_BULL" if bullish else "TRENDING_BEAR",
            "NORMAL",
            Decimal(trend_score),
        ),
        liquidity=LiquidityResult(
            Decimal("1000"),
            Decimal("1500"),
            Decimal(volume_ratio),
            Decimal(liquidity_score),
        ),
        score=Decimal("95"),
    )


def _closed_position(position_id: str = "P-SETTLE") -> Position:
    opened = datetime(2026, 1, 1, tzinfo=UTC)
    decision = json.dumps(
        {
            "setup": "BREAKOUT_RETEST",
            "market_regime": "TRENDING_BULL",
            "risk": {"new_risk": "50"},
        },
        sort_keys=True,
    )
    return Position(
        position_id=position_id,
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("1000"),
        quantity=Decimal("10"),
        leverage=Decimal("1"),
        take_profit=Decimal("110"),
        status=PositionStatus.CLOSED,
        opened_at=opened,
        closed_at=opened + timedelta(hours=2),
        exit_price=Decimal("110"),
        realized_pnl=Decimal("100"),
        close_reason="TAKE_PROFIT",
        decision_snapshot=decision,
    )


def _initialize_equity(connection, amount: Decimal = Decimal("10000")) -> None:
    connection.execute(
        "INSERT INTO account_state(account_id, equity) VALUES (?, ?)",
        ("default", str(amount)),
    )
    connection.commit()


def test_extended_indicator_snapshot_is_computed_and_bounded() -> None:
    snapshot = build_snapshot([_candle(index) for index in range(260)])

    assert snapshot.sma50 is not None
    assert snapshot.macd_line is not None
    assert snapshot.macd_signal is not None
    assert snapshot.macd_histogram is not None
    assert snapshot.adx14 is not None
    assert Decimal("0") <= snapshot.adx14 <= Decimal("100")
    assert snapshot.supertrend_direction in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert snapshot.vwap20 is not None
    assert snapshot.bollinger_lower is not None
    assert snapshot.bollinger_middle is not None
    assert snapshot.bollinger_upper is not None
    assert snapshot.bollinger_lower <= snapshot.bollinger_middle <= snapshot.bollinger_upper


def test_strategy_evidence_responds_to_confirmation_and_liquidity() -> None:
    daily = _snapshot("1d")
    four_hour = _snapshot("4h")
    one_hour = _snapshot("1h")
    strong_fifteen = _snapshot("15m", liquidity_score="100", volume_ratio="2")
    weak_fifteen = _snapshot(
        "15m",
        bullish=False,
        trend_score="50",
        structure_score="50",
        liquidity_score="20",
        volume_ratio="0.4",
    )

    strong = build_strategy_evidence(
        daily,
        four_hour,
        one_hour,
        strong_fifteen,
        setup="CONTINUATION",
        direction="LONG",
        rr=Decimal("3"),
    )
    weak = build_strategy_evidence(
        daily,
        four_hour,
        one_hour,
        weak_fifteen,
        setup="CONTINUATION",
        direction="LONG",
        rr=Decimal("3"),
    )

    assert strong.confirmation_quality > weak.confirmation_quality
    assert strong.liquidity_quality > weak.liquidity_quality
    assert strong.score_breakdown.total > weak.score_breakdown.total


def test_pending_risk_reservation_is_explicit_and_conservative() -> None:
    limit_order = OrderRequest(
        order_id="L-1",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        requested_price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("115"),
        leverage=Decimal("2"),
    )
    market_order = OrderRequest(
        order_id="M-1",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        requested_price=None,
        stop_loss=Decimal("90"),
        take_profit=Decimal("120"),
        leverage=Decimal("1"),
    )

    reservation = reserve_pending_order_risk([limit_order, market_order])

    assert reservation.order_risk["L-1"] == Decimal("50")
    assert reservation.total_risk == Decimal("50")
    assert reservation.unresolved_order_ids == ("M-1",)


def test_correlation_matrix_aggregates_positive_cluster_risk_only() -> None:
    position = Position(
        position_id="BTC-1",
        symbol="BTC/USDT",
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        total_amount=Decimal("1000"),
        quantity=Decimal("10"),
    )
    matrix = CorrelationMatrix(
        (
            CorrelationPair("BTC/USDT", "ETH/USDT", Decimal("0.8")),
            CorrelationPair("BTC/USDT", "SOL/USDT", Decimal("-0.5")),
        )
    )

    eth = matrix.candidate_exposure(
        candidate_symbol="ETH/USDT",
        new_risk=Decimal("40"),
        positions=[position],
    )
    sol = matrix.candidate_exposure(
        candidate_symbol="SOL/USDT",
        new_risk=Decimal("40"),
        positions=[position],
    )

    assert eth.correlated_risk == Decimal("80")
    assert eth.members == ("ETH/USDT", "BTC/USDT")
    assert sol.correlated_risk == Decimal("40")
    assert sol.members == ("SOL/USDT",)


def test_journal_r_multiple_uses_recorded_initial_risk() -> None:
    entry = JournalEntry.from_position(_closed_position())

    assert entry.initial_risk_amount == Decimal("50")
    assert entry.realized_r_multiple == Decimal("2")
    assert entry.decision["setup"] == "BREAKOUT_RETEST"


def test_atomic_settlement_is_exactly_once(tmp_path: Path) -> None:
    connection = connect(tmp_path / "settlement.db")
    _initialize_equity(connection)
    account = Account(starting_equity=Decimal("10000"))
    service = PositionSettlementService(
        connection=connection,
        position_repository=SQLitePositionRepository(connection, auto_commit=False),
        account_repository=SQLiteAccountRepository(connection, auto_commit=False),
        ledger_repository=SQLiteAccountLedgerRepository(connection, auto_commit=False),
        journal_repository=SQLiteJournalRepository(connection, auto_commit=False),
        account=account,
    )
    position = _closed_position()

    first = service.settle(position, cycle_id="C-1")
    second = service.settle(position, cycle_id="C-1")

    assert first.applied is True
    assert second.applied is False
    assert account.equity == Decimal("10100")
    assert SQLiteAccountRepository(connection).load_equity() == Decimal("10100")
    assert connection.execute("SELECT COUNT(*) FROM account_ledger").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM trade_journal").fetchone()[0] == 1
    connection.close()


def test_atomic_settlement_rolls_back_every_persistent_write(tmp_path: Path) -> None:
    class FailingJournal:
        def save(self, entry: JournalEntry) -> bool:
            raise RuntimeError(f"forced journal failure for {entry.position_id}")

        def get(self, position_id: str) -> JournalEntry | None:
            return None

        def list_all(self, symbol: str | None = None) -> list[JournalEntry]:
            return []

    connection = connect(tmp_path / "rollback.db")
    _initialize_equity(connection)
    account = Account(starting_equity=Decimal("10000"))
    service = PositionSettlementService(
        connection=connection,
        position_repository=SQLitePositionRepository(connection, auto_commit=False),
        account_repository=SQLiteAccountRepository(connection, auto_commit=False),
        ledger_repository=SQLiteAccountLedgerRepository(connection, auto_commit=False),
        journal_repository=FailingJournal(),
        account=account,
    )

    with pytest.raises(RuntimeError, match="forced journal failure"):
        service.settle(_closed_position("P-ROLLBACK"), cycle_id="C-2")

    assert connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM account_ledger").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM trade_journal").fetchone()[0] == 0
    assert SQLiteAccountRepository(connection).load_equity() == Decimal("10000")
    assert account.equity == Decimal("10000")
    connection.close()


def test_yahoo_four_hour_aggregation_preserves_ohlcv() -> None:
    bars = [
        Candle(
            "TEST",
            "1h",
            datetime(2026, 1, 1, hour=index, tzinfo=UTC),
            Decimal(str(100 + index)),
            Decimal(str(102 + index)),
            Decimal(str(99 + index)),
            Decimal(str(101 + index)),
            Decimal("10"),
        )
        for index in range(4)
    ]

    aggregated = YahooFinanceProvider._aggregate_four_hour(bars, "TEST")

    assert len(aggregated) == 1
    candle = aggregated[0]
    assert candle.timeframe == "4h"
    assert candle.open == Decimal("100")
    assert candle.high == Decimal("105")
    assert candle.low == Decimal("99")
    assert candle.close == Decimal("104")
    assert candle.volume == Decimal("40")


def test_session_gap_can_be_degraded_instead_of_invalid() -> None:
    first = _candle(0)
    second = _candle(4)

    strict = validate_candles([first, second], expected_timeframe="1h")
    session_aware = validate_candles(
        [first, second], expected_timeframe="1h", allow_session_gaps=True
    )

    assert strict.valid is False
    assert session_aware.valid is True
    assert session_aware.status == "DEGRADED"
    assert session_aware.warnings


def test_paper_composition_builds_without_network_and_requires_explicit_selection(
    tmp_path: Path,
) -> None:
    application = build_paper_application(
        db_path=tmp_path / "paper.db",
        universe_path=Path("config/universe.json"),
    )
    try:
        assert application.mode is SystemMode.PAPER
        assert len(application.registry.all(tradable_only=True)) == 10
        assert application.selection_queue.drain() == []
        readiness = application.health.readiness()
        assert readiness.ready is True
        assert application.api.readiness().status_code == 200
        assert application.position_repository.list_open() == []
    finally:
        application.close()
