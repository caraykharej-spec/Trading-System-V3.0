from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from app.context.models import NewsImpact

from .models import ClassificationResult, IntelligenceCategory, NormalizedNewsRecord, RelevanceResult


_CATEGORY_KEYWORDS: Mapping[IntelligenceCategory, tuple[str, ...]] = {
    IntelligenceCategory.MACRO: ("inflation", "cpi", "jobs", "payroll", "rates", "fed", "ecb", "gdp"),
    IntelligenceCategory.REGULATORY: ("sec", "regulator", "regulation", "lawsuit", "approval", "ban"),
    IntelligenceCategory.SECURITY: ("hack", "exploit", "breach", "attack", "stolen"),
    IntelligenceCategory.EXCHANGE: ("exchange", "listing", "delisting", "withdrawal", "deposit"),
    IntelligenceCategory.PROTOCOL: ("upgrade", "fork", "mainnet", "validator", "protocol"),
    IntelligenceCategory.CORPORATE: ("earnings", "revenue", "guidance", "merger", "acquisition"),
    IntelligenceCategory.MARKET_STRUCTURE: ("liquidation", "open interest", "funding", "etf flow", "inflow", "outflow"),
}
_POSITIVE: tuple[str, ...] = (
    "approval", "approved", "upgrade", "surge", "record high", "beats", "strong growth",
    "inflow", "partnership", "adoption", "launch",
)
_NEGATIVE: tuple[str, ...] = (
    "ban", "lawsuit", "hack", "exploit", "breach", "delisting", "outflow", "misses",
    "downgrade", "default", "investigation", "shutdown",
)


class RuleBasedIntelligenceClassifier:
    """Deterministic baseline classifier; replaceable by an external NLP model later."""

    def __init__(
        self,
        *,
        category_keywords: Mapping[IntelligenceCategory, Sequence[str]] | None = None,
    ) -> None:
        self.category_keywords = category_keywords or _CATEGORY_KEYWORDS

    def classify(
        self,
        record: NormalizedNewsRecord,
        relevance: RelevanceResult,
    ) -> ClassificationResult:
        text = f"{record.title} {record.body}".casefold()
        category = IntelligenceCategory.OTHER
        category_evidence = 0
        for candidate, keywords in self.category_keywords.items():
            hits = sum(1 for keyword in keywords if keyword.casefold() in text)
            if hits > category_evidence:
                category = candidate
                category_evidence = hits

        positive = sum(1 for keyword in _POSITIVE if keyword in text)
        negative = sum(1 for keyword in _NEGATIVE if keyword in text)
        if positive > negative:
            impact = NewsImpact.SUPPORTIVE
        elif negative > positive:
            impact = NewsImpact.ADVERSE
        elif positive or negative:
            impact = NewsImpact.NEUTRAL
        else:
            impact = NewsImpact.UNKNOWN

        directional_evidence = abs(positive - negative)
        confidence = Decimal("0.35")
        confidence += min(Decimal("0.30"), Decimal(category_evidence) * Decimal("0.10"))
        confidence += min(Decimal("0.20"), Decimal(directional_evidence) * Decimal("0.10"))
        confidence += relevance.score * Decimal("0.15")
        return ClassificationResult(
            category=category,
            impact=impact,
            confidence=min(Decimal("0.95"), confidence),
        )
