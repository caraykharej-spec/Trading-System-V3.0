from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable

from .models import AssistantIntent


_PERCENT_PATTERN = re.compile(r"(?P<value>[+-]?\d+(?:\.\d+)?)\s*%")


@dataclass(frozen=True)
class IntentRoute:
    intent: AssistantIntent
    symbol: str | None = None
    scenario_percent: Decimal | None = None


class AssistantIntentRouter:
    """Deterministic intent router for evidence retrieval.

    The router never generates trading decisions. It only chooses which
    grounded evidence should be presented to the conversation layer.
    """

    _HELP_TERMS = ("help", "what can you", "راهنما", "چه کار")
    _WHAT_IF_TERMS = ("what if", "what-if", "scenario", "suppose", "اگر", "سناریو", "فرض کن")
    _DOWN_TERMS = ("down", "drop", "falls", "fall", "decrease", "decline", "کاهش", "ریزش", "پایین")
    _UP_TERMS = ("up", "rise", "rises", "increase", "gains", "رشد", "افزایش", "بالا")
    _POSITION_TERMS = ("position", "positions", "open trade", "open trades", "پوزیشن", "معامله باز")
    _JOURNAL_TERMS = ("journal", "trade history", "trading history", "performance history", "ژورنال", "سابقه معاملات")
    _MARKET_CHANGE_TERMS = (
        "market change",
        "what changed",
        "changed",
        "change since",
        "movement",
        "تغییر بازار",
        "چه تغییری",
        "تغییر کرده",
    )
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

    @classmethod
    def _extract_scenario_percent(cls, normalized: str) -> Decimal | None:
        match = _PERCENT_PATTERN.search(normalized)
        if match is None:
            return None
        value = Decimal(match.group("value"))
        if not match.group("value").startswith(("+", "-")):
            if any(term in normalized for term in cls._DOWN_TERMS):
                value = -value
            elif any(term in normalized for term in cls._UP_TERMS):
                value = abs(value)
        if value <= Decimal("-100") or value > Decimal("1000"):
            raise ValueError("what-if percent must be greater than -100 and at most 1000")
        return value

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
        if any(term in normalized for term in self._WHAT_IF_TERMS):
            return IntentRoute(
                AssistantIntent.WHAT_IF,
                symbol,
                self._extract_scenario_percent(normalized),
            )
        if any(term in normalized for term in self._POSITION_TERMS):
            return IntentRoute(AssistantIntent.POSITIONS, symbol)
        if any(term in normalized for term in self._JOURNAL_TERMS):
            return IntentRoute(AssistantIntent.JOURNAL, symbol)
        if any(term in normalized for term in self._MARKET_CHANGE_TERMS):
            return IntentRoute(AssistantIntent.MARKET_CHANGE, symbol)
        if symbol is not None and any(term in normalized for term in self._REJECTION_TERMS):
            return IntentRoute(AssistantIntent.REJECTION_REASON, symbol)
        if any(term in normalized for term in self._RISK_TERMS):
            return IntentRoute(AssistantIntent.RISK_SUMMARY, symbol)
        if symbol is not None:
            return IntentRoute(AssistantIntent.SYMBOL_EXPLANATION, symbol)
        if any(term in normalized for term in self._MARKET_TERMS):
            return IntentRoute(AssistantIntent.MARKET_BRIEF)
        return IntentRoute(AssistantIntent.UNKNOWN)
