from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CopilotStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    HOLD = "HOLD"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class EvidenceFact:
    key: str
    value: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value, "source": self.source}


@dataclass(frozen=True)
class CopilotItemBrief:
    symbol: str
    status: CopilotStatus
    title: str
    narrative: tuple[str, ...]
    facts: tuple[EvidenceFact, ...] = ()
    reasons: tuple[str, ...] = ()
    rank: int | None = None
    execution_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status.value,
            "title": self.title,
            "narrative": list(self.narrative),
            "facts": [fact.to_dict() for fact in self.facts],
            "reasons": list(self.reasons),
            "rank": self.rank,
            "execution_authority": self.execution_authority,
        }


@dataclass(frozen=True)
class CopilotMarketBrief:
    evaluated: int
    strategy_qualified: int
    context_rejected: int
    risk_rejected: int
    portfolio_rejected: int
    items: tuple[CopilotItemBrief, ...]
    execution_authority: bool = False
    disclaimer: str = (
        "Explanatory evidence only; this response cannot submit orders or bypass trading gates."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "strategy_qualified": self.strategy_qualified,
            "context_rejected": self.context_rejected,
            "risk_rejected": self.risk_rejected,
            "portfolio_rejected": self.portfolio_rejected,
            "items": [item.to_dict() for item in self.items],
            "execution_authority": self.execution_authority,
            "disclaimer": self.disclaimer,
        }
