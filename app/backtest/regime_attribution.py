from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any, Iterable, Sequence

from app.data.market_data import Candle
from app.market.regime import classify_regime
from app.market.trend import analyze_trend

from .diagnostics import BacktestDiagnosticEvent
from .models import TradeRecord

_DECISION_CODES = {
    "DECISION_NO_SNAPSHOT",
    "STRATEGY_PRE_SIGNAL_REJECT",
    "STRATEGY_SIGNAL_REJECT",
    "READY_FOR_RISK_REVIEW",
}
_DECIMAL_RECONCILIATION_PRECISION = 128


@dataclass(frozen=True)
class RegimePoint:
    effective_at: datetime
    regime: str
    volatility: str


def _precise_sum(values: Iterable[Decimal]) -> Decimal:
    """Sum financial Decimal values without order-dependent context rounding."""

    with localcontext() as context:
        context.prec = _DECIMAL_RECONCILIATION_PRECISION
        return sum(values, Decimal("0"))


def build_daily_regime_timeline(
    symbol: str,
    daily_candles: Sequence[Candle],
) -> tuple[RegimePoint, ...]:
    """Build a no-lookahead 1D regime timeline from completed daily candles."""

    del symbol
    ordered = sorted(daily_candles, key=lambda candle: candle.timestamp)
    points: list[RegimePoint] = []
    history: list[Candle] = []
    for candle in ordered:
        history.append(candle)
        trend = analyze_trend(history)
        regime = classify_regime(history, trend)
        points.append(
            RegimePoint(
                effective_at=candle.timestamp + timedelta(days=1),
                regime=regime.regime,
                volatility=regime.volatility,
            )
        )
    return tuple(points)


def _bucket_for(timestamp: datetime, timeline: Sequence[RegimePoint]) -> RegimePoint:
    if not timeline:
        raise ValueError("regime timeline is empty")
    index = bisect_right(
        timeline,
        timestamp,
        key=lambda point: point.effective_at,
    ) - 1
    if index < 0:
        raise ValueError(
            f"no completed daily regime is available at {timestamp.isoformat()}"
        )
    return timeline[index]


def _trade_metrics(
    trades: Iterable[TradeRecord],
    timeline: Sequence[RegimePoint],
    initial_equity: Decimal,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    by_regime: dict[str, list[TradeRecord]] = defaultdict(list)
    by_combined: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        point = _bucket_for(trade.entry_time, timeline)
        by_regime[point.regime].append(trade)
        by_combined[f"{point.regime}|{point.volatility}"].append(trade)

    def summarize(rows: list[TradeRecord]) -> dict[str, object]:
        pnls = [trade.realized_pnl for trade in rows]
        positive = _precise_sum(pnl for pnl in pnls if pnl > 0)
        negative = _precise_sum(pnl for pnl in pnls if pnl < 0)
        wins = sum(1 for pnl in pnls if pnl > 0)
        losses = sum(1 for pnl in pnls if pnl < 0)
        breakeven = len(pnls) - wins - losses
        net_pnl = _precise_sum(pnls)
        profit_factor: Decimal | None
        if negative < 0:
            with localcontext() as context:
                context.prec = _DECIMAL_RECONCILIATION_PRECISION
                profit_factor = positive / abs(negative)
        elif positive > 0:
            profit_factor = None
        else:
            profit_factor = Decimal("0") if rows else None
        with localcontext() as context:
            context.prec = _DECIMAL_RECONCILIATION_PRECISION
            win_rate = (
                Decimal(wins) / Decimal(len(rows)) * Decimal("100")
                if rows
                else Decimal("0")
            )
            contribution = (
                net_pnl / initial_equity * Decimal("100")
                if initial_equity > 0
                else Decimal("0")
            )
        return {
            "trade_count": len(rows),
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate_percent": win_rate,
            "net_pnl": net_pnl,
            "net_pnl_percent_initial_equity": contribution,
            "profit_factor": profit_factor,
        }

    return (
        {key: summarize(rows) for key, rows in sorted(by_regime.items())},
        {key: summarize(rows) for key, rows in sorted(by_combined.items())},
    )


def attribute_regime_evidence(
    events: Sequence[BacktestDiagnosticEvent],
    trades: Sequence[TradeRecord],
    timeline: Sequence[RegimePoint],
    *,
    initial_equity: Decimal,
) -> dict[str, Any]:
    """Attribute the unchanged baseline decision path to 1D regime/volatility."""

    regime_counts: dict[str, Counter[str]] = defaultdict(Counter)
    volatility_counts: dict[str, Counter[str]] = defaultdict(Counter)
    combined_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for event in events:
        point = _bucket_for(event.timestamp, timeline)
        combined = f"{point.regime}|{point.volatility}"
        for target in (
            regime_counts[point.regime],
            volatility_counts[point.volatility],
            combined_counts[combined],
        ):
            target[event.code] += 1
            if event.code in _DECISION_CODES:
                target["DECISION_POINTS"] += 1

    trade_by_regime, trade_by_combined = _trade_metrics(
        trades,
        timeline,
        initial_equity,
    )

    def serialize(counter_map: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
        return {
            key: dict(sorted(counter.items()))
            for key, counter in sorted(counter_map.items())
        }

    return {
        "schema_version": "1.0",
        "primary_regime_timeframe": "1d",
        "classification_semantics": (
            "Each event is attributed to the latest fully completed 1D candle at or before the event timestamp."
        ),
        "regime_model": {
            "trend_labels": ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "UNKNOWN"],
            "volatility_high_rule": "average normalized high-low range over last 20 completed daily candles >= 0.03",
            "volatility_low_rule": "average normalized high-low range over last 20 completed daily candles <= 0.01",
            "volatility_normal_rule": "otherwise NORMAL",
        },
        "event_counts_by_regime": serialize(regime_counts),
        "event_counts_by_volatility": serialize(volatility_counts),
        "event_counts_by_regime_and_volatility": serialize(combined_counts),
        "trade_performance_by_entry_regime": trade_by_regime,
        "trade_performance_by_entry_regime_and_volatility": trade_by_combined,
    }


def validate_regime_attribution(
    payload: dict[str, Any],
    *,
    expected_decision_points: int,
    expected_ready: int,
    expected_entry_rejections: int,
    expected_trades: int,
    trades: Sequence[TradeRecord],
) -> None:
    event_counts = payload["event_counts_by_regime"]
    decision_points = sum(
        int(bucket.get("DECISION_POINTS", 0)) for bucket in event_counts.values()
    )
    ready = sum(
        int(bucket.get("READY_FOR_RISK_REVIEW", 0)) for bucket in event_counts.values()
    )
    entry_rejections = sum(
        int(bucket.get("ENTRY_REJECT", 0)) for bucket in event_counts.values()
    )
    trades_opened = sum(
        int(bucket.get("TRADE_OPENED", 0)) for bucket in event_counts.values()
    )
    if decision_points != expected_decision_points:
        raise RuntimeError("regime attribution decision-point accounting mismatch")
    if ready != expected_ready:
        raise RuntimeError("regime attribution READY accounting mismatch")
    if entry_rejections != expected_entry_rejections:
        raise RuntimeError("regime attribution entry-rejection accounting mismatch")
    if trades_opened != expected_trades:
        raise RuntimeError("regime attribution trade-open accounting mismatch")

    trade_metrics = payload["trade_performance_by_entry_regime"]
    attributed_trade_count = sum(
        int(bucket["trade_count"]) for bucket in trade_metrics.values()
    )
    if attributed_trade_count != expected_trades:
        raise RuntimeError("regime attribution closed-trade accounting mismatch")

    attributed_pnl = _precise_sum(
        Decimal(str(bucket["net_pnl"])) for bucket in trade_metrics.values()
    )
    actual_pnl = _precise_sum(trade.realized_pnl for trade in trades)
    if attributed_pnl != actual_pnl:
        raise RuntimeError(
            "regime attribution PnL accounting mismatch: "
            f"attributed={attributed_pnl} actual={actual_pnl}"
        )
