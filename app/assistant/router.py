from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import AssistantIntent


@dataclass(frozen=True)
class IntentRoute:
    intent: AssistantIntent
    symbol: str | None = None


class AssistantIntentRouter:
    """Deterministic intent router for evidence retrieval.

    The router never generates trading decisions. It only chooses which
    grounded copilot evidence should be presented to the conversation layer.
    """

    _HELP_TERMS = ("help", "what can you", "راهنما", "چه کار")
    _REJECTION_TERMS = (
        "why rejected",
        "why was",
        "rejected",
        "reject",
        "hold",
        "blocked",
        "چرا رد",
        "رد شد",
        "هولد",
    )
    _RISK_TERMS = ("risk", "exposure", "capital", "ریسک", "سرمایه")
    _MARKET_TERMS = (
        "market",
        "brief",
        "ranking",
        "rank",
        "opportunities",
        "بازار",
        "رنک",
        "رتبه",
        "فرصت",
    )
    _FOLLOW_UP_TERMS = ("it", "its", "this", "that", "این", "آن", "همین")

    @staticmethod
    def _extract_symbol(query: str, symbols: Iterable[str]) -> str | None:
        normalized = query.upper().replace("/", "").replace("-", "")
        for symbol in sorted({item.upper() for item in symbols}, key=len, reverse=True):
            compact = symbol.replace("/", "").replace("-", "")
            if compact and compact in normalized:
                return symbol
        return None

    def route(
        self,
        query: str,
        symbols: Iterable[str],
        *,
        last_symbol: str | None = None,
    ) -> IntentRoute:
        normalized = " ".join(query.strip().lower().split())
        if not normalized:
            raise ValueError("assistant query must not be empty")

        symbol = self._extract_symbol(query, symbols)
        if symbol is None and last_symbol is not None:
            if any(term in normalized for term in self._FOLLOW_UP_TERMS):
                symbol = last_symbol.upper()

        if any(term in normalized for term in self._HELP_TERMS):
            return IntentRoute(AssistantIntent.HELP, symbol)
        if symbol is not None and any(term in normalized for term in self._REJECTION_TERMS):
            return IntentRoute(AssistantIntent.REJECTION_REASON, symbol)
        if any(term in normalized for term in self._RISK_TERMS):
            return IntentRoute(AssistantIntent.RISK_SUMMARY, symbol)
        if symbol is not None:
            return IntentRoute(AssistantIntent.SYMBOL_EXPLANATION, symbol)
        if any(term in normalized for term in self._MARKET_TERMS):
            return IntentRoute(AssistantIntent.MARKET_BRIEF)
        return IntentRoute(AssistantIntent.UNKNOWN)
