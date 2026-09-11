from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AssistantIntent(str, Enum):
    MARKET_BRIEF = "MARKET_BRIEF"
    SYMBOL_EXPLANATION = "SYMBOL_EXPLANATION"
    REJECTION_REASON = "REJECTION_REASON"
    RISK_SUMMARY = "RISK_SUMMARY"
    POSITIONS = "POSITIONS"
    JOURNAL = "JOURNAL"
    MARKET_CHANGE = "MARKET_CHANGE"
    WHAT_IF = "WHAT_IF"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


class AnswerMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    MODEL = "MODEL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceCitation:
    citation_id: str
    key: str
    value: str
    source: str
    symbol: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "citation_id": self.citation_id,
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "symbol": self.symbol,
        }


@dataclass(frozen=True)
class GroundingBundle:
    intent: AssistantIntent
    query: str
    citations: tuple[EvidenceCitation, ...]
    deterministic_lines: tuple[str, ...]
    symbol: str | None = None
    missing: tuple[str, ...] = ()
    execution_authority: bool = False


@dataclass(frozen=True)
class AssistantResponse:
    intent: AssistantIntent
    text: str
    citations: tuple[EvidenceCitation, ...]
    mode: AnswerMode
    symbol: str | None = None
    grounded: bool = True
    unknowns: tuple[str, ...] = ()
    model_used: bool = False
    execution_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "text": self.text,
            "citations": [item.to_dict() for item in self.citations],
            "mode": self.mode.value,
            "symbol": self.symbol,
            "grounded": self.grounded,
            "unknowns": list(self.unknowns),
            "model_used": self.model_used,
            "execution_authority": self.execution_authority,
        }
