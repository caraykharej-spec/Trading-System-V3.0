from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json

from app.core.enums import PositionSide, PositionStatus
from app.core.models import Position


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class JournalEntry:
    """Immutable factual record of one completed position and its decision provenance."""

    position_id: str
    symbol: str
    side: PositionSide
    entry_price: Decimal
    exit_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal | None
    total_amount: Decimal
    quantity: Decimal
    leverage: Decimal
    realized_pnl: Decimal
    opened_at: datetime
    closed_at: datetime
    close_reason: str
    cycle_id: str | None = None
    decision_snapshot: str | None = None

    def __post_init__(self) -> None:
        if not self.position_id.strip():
            raise ValueError("position_id must not be empty")
        if not self.symbol.strip():
            raise ValueError("symbol must not be empty")
        if self.entry_price <= 0 or self.exit_price <= 0 or self.stop_loss <= 0:
            raise ValueError("prices must be positive")
        if self.take_profit is not None and self.take_profit <= 0:
            raise ValueError("take_profit must be positive when provided")
        if self.total_amount <= 0 or self.quantity <= 0 or self.leverage <= 0:
            raise ValueError("position sizing values must be positive")
        if not self.close_reason.strip():
            raise ValueError("close_reason must not be empty")
        if self.cycle_id is not None and not self.cycle_id.strip():
            raise ValueError("cycle_id must not be empty when provided")
        if self.decision_snapshot is not None:
            try:
                payload = json.loads(self.decision_snapshot)
            except json.JSONDecodeError as exc:
                raise ValueError("decision_snapshot must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("decision_snapshot must contain a JSON object")
        _require_aware(self.opened_at, "opened_at")
        _require_aware(self.closed_at, "closed_at")
        if self.closed_at < self.opened_at:
            raise ValueError("closed_at cannot be before opened_at")

    @property
    def return_percent(self) -> Decimal:
        """Realized P&L as a percentage of recorded position amount."""
        return self.realized_pnl / self.total_amount * Decimal("100")

    @property
    def decision(self) -> dict[str, object]:
        if self.decision_snapshot is None:
            return {}
        payload = json.loads(self.decision_snapshot)
        return payload if isinstance(payload, dict) else {}

    @property
    def initial_risk_amount(self) -> Decimal | None:
        risk = self.decision.get("risk")
        if not isinstance(risk, dict):
            return None
        value = risk.get("new_risk")
        return Decimal(str(value)) if value is not None else None

    @property
    def realized_r_multiple(self) -> Decimal | None:
        initial_risk = self.initial_risk_amount
        if initial_risk is None or initial_risk <= 0:
            return None
        return self.realized_pnl / initial_risk

    @classmethod
    def from_position(
        cls, position: Position, cycle_id: str | None = None
    ) -> "JournalEntry":
        if position.status is PositionStatus.OPEN:
            raise ValueError("cannot journal an open position")
        if position.closed_at is None:
            raise ValueError("closed position is missing closed_at")
        if position.exit_price is None:
            raise ValueError("closed position is missing exit_price")
        if position.realized_pnl is None:
            raise ValueError("closed position is missing realized_pnl")
        if not position.close_reason:
            raise ValueError("closed position is missing close_reason")
        return cls(
            position_id=position.position_id,
            symbol=position.symbol,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=position.exit_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            total_amount=position.total_amount,
            quantity=position.quantity,
            leverage=position.leverage,
            realized_pnl=position.realized_pnl,
            opened_at=position.opened_at,
            closed_at=position.closed_at,
            close_reason=position.close_reason,
            cycle_id=cycle_id,
            decision_snapshot=position.decision_snapshot,
        )
