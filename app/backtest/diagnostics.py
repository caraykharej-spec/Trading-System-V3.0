from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BacktestDiagnosticEvent:
    timestamp: datetime
    code: str
    reasons: tuple[str, ...] = ()
    direction: str | None = None
    setup: str | None = None
    rr: Decimal | None = None
    score: Decimal | None = None
    confidence: Decimal | None = None


class SignalAttritionDiagnostics:
    """Read-only aggregation of the exact BacktestEngine decision path."""

    _DECISION_CODES = {
        "DECISION_NO_SNAPSHOT",
        "STRATEGY_PRE_SIGNAL_REJECT",
        "STRATEGY_SIGNAL_REJECT",
        "READY_FOR_RISK_REVIEW",
    }

    def __init__(self) -> None:
        self._event_counts: Counter[str] = Counter()
        self._pre_signal_reasons: Counter[str] = Counter()
        self._post_signal_reasons: Counter[str] = Counter()
        self._entry_reasons: Counter[str] = Counter()
        self._ready_directions: Counter[str] = Counter()
        self._ready_setups: Counter[str] = Counter()
        self._trade_directions: Counter[str] = Counter()
        self._trade_setups: Counter[str] = Counter()
        self._post_signal_overlap = 0

    def record(self, event: BacktestDiagnosticEvent) -> None:
        self._event_counts[event.code] += 1
        if event.code == "STRATEGY_PRE_SIGNAL_REJECT":
            for reason in event.reasons:
                self._pre_signal_reasons[reason] += 1
        elif event.code == "STRATEGY_SIGNAL_REJECT":
            if len(event.reasons) > 1:
                self._post_signal_overlap += 1
            for reason in event.reasons:
                self._post_signal_reasons[reason] += 1
        elif event.code == "ENTRY_REJECT":
            for reason in event.reasons:
                self._entry_reasons[reason] += 1
        elif event.code == "READY_FOR_RISK_REVIEW":
            if event.direction is not None:
                self._ready_directions[event.direction] += 1
            if event.setup is not None:
                self._ready_setups[event.setup] += 1
        elif event.code == "TRADE_OPENED":
            if event.direction is not None:
                self._trade_directions[event.direction] += 1
            if event.setup is not None:
                self._trade_setups[event.setup] += 1

    def to_payload(self) -> dict[str, Any]:
        decision_points = sum(self._event_counts[code] for code in self._DECISION_CODES)
        pre_signal_rejections = self._event_counts["STRATEGY_PRE_SIGNAL_REJECT"]
        post_signal_rejections = self._event_counts["STRATEGY_SIGNAL_REJECT"]
        ready = self._event_counts["READY_FOR_RISK_REVIEW"]
        entry_rejections = self._event_counts["ENTRY_REJECT"]
        trades_opened = self._event_counts["TRADE_OPENED"]
        pending_at_end = self._event_counts["PENDING_SIGNAL_END_OF_TEST"]
        entry_attempts = entry_rejections + trades_opened
        legacy_rejected_equivalent = (
            pre_signal_rejections
            + post_signal_rejections
            + self._entry_reasons["SHORT_DISABLED"]
        )
        return {
            "decision_points": decision_points,
            "snapshot_unavailable": self._event_counts["DECISION_NO_SNAPSHOT"],
            "pre_signal_rejections": pre_signal_rejections,
            "pre_signal_reasons": dict(sorted(self._pre_signal_reasons.items())),
            "post_signal_rejections": post_signal_rejections,
            "post_signal_reason_occurrences": dict(
                sorted(self._post_signal_reasons.items())
            ),
            "post_signal_multi_reason_decisions": self._post_signal_overlap,
            "ready_for_risk_review": ready,
            "ready_by_direction": dict(sorted(self._ready_directions.items())),
            "ready_by_setup": dict(sorted(self._ready_setups.items())),
            "entry_attempts": entry_attempts,
            "entry_rejections": entry_rejections,
            "entry_reasons": dict(sorted(self._entry_reasons.items())),
            "trades_opened": trades_opened,
            "trades_by_direction": dict(sorted(self._trade_directions.items())),
            "trades_by_setup": dict(sorted(self._trade_setups.items())),
            "pending_signal_at_end": pending_at_end,
            "legacy_rejected_signals_equivalent": legacy_rejected_equivalent,
        }
