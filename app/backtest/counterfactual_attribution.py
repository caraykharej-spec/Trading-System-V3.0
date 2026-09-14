from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from typing import Any, Iterable, Sequence

from .diagnostics import BacktestDiagnosticEvent
from .models import TradeRecord

_DECIMAL_PRECISION = 128
_POST_SIGNAL_GATES = {
    "R:R below minimum": "MIN_RR",
    "score below minimum": "MIN_SCORE",
    "confidence below minimum": "MIN_CONFIDENCE",
}


def _precise_sum(values: Iterable[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        return sum(values, Decimal("0"))


def _trade_summary(trades: Sequence[TradeRecord]) -> dict[str, object]:
    pnls = [trade.realized_pnl for trade in trades]
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)
    breakeven = len(pnls) - wins - losses
    positive = _precise_sum(pnl for pnl in pnls if pnl > 0)
    negative = _precise_sum(pnl for pnl in pnls if pnl < 0)
    net_pnl = _precise_sum(pnls)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        win_rate = (
            Decimal(wins) / Decimal(len(trades)) * Decimal("100")
            if trades
            else Decimal("0")
        )
        profit_factor: Decimal | None
        if negative < 0:
            profit_factor = positive / abs(negative)
        elif positive > 0:
            profit_factor = None
        else:
            profit_factor = Decimal("0") if trades else None
    return {
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate_percent": win_rate,
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
    }


def _quality_summary(events: Sequence[BacktestDiagnosticEvent]) -> dict[str, object]:
    def summarize(field: str) -> dict[str, object] | None:
        values = [
            value
            for event in events
            if (value := getattr(event, field)) is not None
        ]
        if not values:
            return None
        with localcontext() as context:
            context.prec = _DECIMAL_PRECISION
            average = _precise_sum(values) / Decimal(len(values))
        return {
            "min": min(values),
            "max": max(values),
            "average": average,
        }

    return {
        "rr": summarize("rr"),
        "score": summarize("score"),
        "confidence": summarize("confidence"),
    }


def build_counterfactual_gate_attribution(
    events: Sequence[BacktestDiagnosticEvent],
    trades: Sequence[TradeRecord],
) -> dict[str, Any]:
    """Build research-only marginal attribution without changing execution.

    The report distinguishes exact one-gate releases from candidate-only counts.
    It never invents hypothetical trade PnL for paths the baseline did not execute.
    """

    pre_signal_reasons: Counter[str] = Counter()
    post_reason_occurrences: Counter[str] = Counter()
    post_single_release: Counter[str] = Counter()
    post_single_release_by_direction: dict[str, Counter[str]] = defaultdict(Counter)
    ready_by_direction: Counter[str] = Counter()
    entry_reject_by_reason: Counter[str] = Counter()
    entry_reject_by_direction: dict[str, Counter[str]] = defaultdict(Counter)
    entry_events_by_reason: dict[str, list[BacktestDiagnosticEvent]] = defaultdict(list)
    post_reject_by_direction: Counter[str] = Counter()
    multi_gate_post_rejections = 0

    for event in events:
        if event.code == "STRATEGY_PRE_SIGNAL_REJECT":
            pre_signal_reasons.update(event.reasons)
            continue
        if event.code == "STRATEGY_SIGNAL_REJECT":
            if event.direction is not None:
                post_reject_by_direction[event.direction] += 1
            if len(event.reasons) > 1:
                multi_gate_post_rejections += 1
            for reason in event.reasons:
                post_reason_occurrences[reason] += 1
            if len(event.reasons) == 1:
                reason = event.reasons[0]
                gate = _POST_SIGNAL_GATES.get(reason)
                if gate is not None:
                    post_single_release[gate] += 1
                    if event.direction is not None:
                        post_single_release_by_direction[gate][event.direction] += 1
            continue
        if event.code == "READY_FOR_RISK_REVIEW":
            if event.direction is not None:
                ready_by_direction[event.direction] += 1
            continue
        if event.code == "ENTRY_REJECT":
            for reason in event.reasons:
                entry_reject_by_reason[reason] += 1
                entry_events_by_reason[reason].append(event)
                if event.direction is not None:
                    entry_reject_by_direction[reason][event.direction] += 1

    trades_by_direction: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        trades_by_direction[trade.direction].append(trade)

    directions = sorted(
        set(ready_by_direction)
        | set(post_reject_by_direction)
        | set(trades_by_direction)
        | {
            direction
            for counts in entry_reject_by_direction.values()
            for direction in counts
        }
    )
    direction_flow: dict[str, dict[str, object]] = {}
    for direction in directions:
        entry_rejections = sum(
            counts[direction] for counts in entry_reject_by_direction.values()
        )
        direction_flow[direction] = {
            "post_signal_rejections": post_reject_by_direction[direction],
            "ready_for_risk_review": ready_by_direction[direction],
            "entry_rejections": entry_rejections,
            "trades_opened": len(trades_by_direction[direction]),
            "realized_trade_performance": _trade_summary(trades_by_direction[direction]),
        }

    post_gates: dict[str, dict[str, object]] = {}
    for reason, gate in _POST_SIGNAL_GATES.items():
        post_gates[gate] = {
            "baseline_reason": reason,
            "reason_occurrences": post_reason_occurrences[reason],
            "exact_single_gate_release_candidates": post_single_release[gate],
            "exact_single_gate_release_by_direction": dict(
                sorted(post_single_release_by_direction[gate].items())
            ),
            "interpretation": (
                "These candidates failed only this gate, so removing only this gate would move them to risk review. No hypothetical trade PnL is claimed."
            ),
        }

    risk_gates: dict[str, dict[str, object]] = {}
    for reason in sorted(entry_reject_by_reason):
        risk_gates[reason] = {
            "candidate_count": entry_reject_by_reason[reason],
            "by_direction": dict(sorted(entry_reject_by_direction[reason].items())),
            "signal_quality": _quality_summary(entry_events_by_reason[reason]),
            "interpretation": (
                "Candidate-only sensitivity. Removing this risk gate can change later capital/risk state, so no causal trade-count or PnL counterfactual is claimed."
            ),
        }

    return {
        "schema_version": "1.0",
        "mode": "RESEARCH_ONLY_NO_EXECUTION_CHANGE",
        "pre_signal_observed_attrition": dict(sorted(pre_signal_reasons.items())),
        "pre_signal_interpretation": (
            "Observed first-failure counts only. HTF/setup/level gates do not have a uniquely defined downstream counterfactual path, so hypothetical PnL is intentionally not generated."
        ),
        "post_signal_gate_sensitivity": post_gates,
        "post_signal_multi_gate_rejections": multi_gate_post_rejections,
        "risk_gate_candidate_sensitivity": risk_gates,
        "direction_flow": direction_flow,
        "direction_performance_scope": (
            "Performance uses only trades actually opened by the frozen baseline. It is attribution, not a causal simulation of disabling LONG or SHORT."
        ),
    }


def validate_counterfactual_gate_attribution(
    payload: dict[str, Any],
    *,
    expected_ready: int,
    expected_entry_rejections: int,
    expected_trades: int,
    trades: Sequence[TradeRecord],
) -> None:
    direction_flow = payload["direction_flow"]
    ready = sum(int(row["ready_for_risk_review"]) for row in direction_flow.values())
    entry_rejections = sum(int(row["entry_rejections"]) for row in direction_flow.values())
    trades_opened = sum(int(row["trades_opened"]) for row in direction_flow.values())
    if ready != expected_ready:
        raise RuntimeError("counterfactual attribution READY accounting mismatch")
    if entry_rejections != expected_entry_rejections:
        raise RuntimeError("counterfactual attribution entry-rejection accounting mismatch")
    if trades_opened != expected_trades:
        raise RuntimeError("counterfactual attribution trade-open accounting mismatch")

    attributed_pnl = _precise_sum(
        Decimal(str(row["realized_trade_performance"]["net_pnl"]))
        for row in direction_flow.values()
    )
    actual_pnl = _precise_sum(trade.realized_pnl for trade in trades)
    if attributed_pnl != actual_pnl:
        raise RuntimeError(
            "counterfactual attribution PnL accounting mismatch: "
            f"attributed={attributed_pnl} actual={actual_pnl}"
        )
