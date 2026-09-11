from __future__ import annotations

from app.copilot.models import CopilotItemBrief, CopilotMarketBrief, CopilotStatus

from .models import AssistantIntent, EvidenceCitation, GroundingBundle
from .router import IntentRoute


def _citation_id(symbol: str, source: str, key: str) -> str:
    safe_symbol = symbol.upper().replace("/", "_").replace("-", "_")
    safe_source = source.lower().replace(" ", "_")
    safe_key = key.lower().replace(" ", "_")
    return f"{safe_symbol}:{safe_source}:{safe_key}"


def _item_citations(item: CopilotItemBrief) -> tuple[EvidenceCitation, ...]:
    citations: list[EvidenceCitation] = [
        EvidenceCitation(
            citation_id=_citation_id(item.symbol, "copilot", "status"),
            key="status",
            value=item.status.value,
            source="copilot",
            symbol=item.symbol,
        )
    ]
    if item.rank is not None:
        citations.append(
            EvidenceCitation(
                citation_id=_citation_id(item.symbol, "copilot", "rank"),
                key="rank",
                value=str(item.rank),
                source="copilot",
                symbol=item.symbol,
            )
        )
    for fact in item.facts:
        citations.append(
            EvidenceCitation(
                citation_id=_citation_id(item.symbol, fact.source, fact.key),
                key=fact.key,
                value=fact.value,
                source=fact.source,
                symbol=item.symbol,
            )
        )
    for index, reason in enumerate(item.reasons, start=1):
        citations.append(
            EvidenceCitation(
                citation_id=_citation_id(item.symbol, "gate_reason", str(index)),
                key=f"reason_{index}",
                value=reason,
                source="gate_reason",
                symbol=item.symbol,
            )
        )
    return tuple(citations)


def _find_item(brief: CopilotMarketBrief, symbol: str | None) -> CopilotItemBrief | None:
    if symbol is None:
        return None
    target = symbol.upper()
    return next((item for item in brief.items if item.symbol.upper() == target), None)


class GroundingBuilder:
    """Build the only evidence payload an LLM narrator may receive."""

    def build(
        self,
        route: IntentRoute,
        query: str,
        brief: CopilotMarketBrief,
    ) -> GroundingBundle:
        if route.intent is AssistantIntent.HELP:
            return GroundingBundle(
                intent=route.intent,
                query=query,
                symbol=route.symbol,
                citations=(),
                deterministic_lines=(
                    "I can explain the current market brief, a symbol's recorded evidence, "
                    "risk facts, or why a candidate was held/rejected.",
                    "I cannot submit orders, change risk limits, or activate live trading.",
                ),
            )
        if route.intent is AssistantIntent.MARKET_BRIEF:
            return self._market_brief(query, brief)
        if route.intent is AssistantIntent.RISK_SUMMARY:
            return self._risk_summary(query, route.symbol, brief)
        if route.intent is AssistantIntent.REJECTION_REASON:
            return self._rejection(query, route.symbol, brief)
        if route.intent is AssistantIntent.SYMBOL_EXPLANATION:
            return self._symbol(query, route.symbol, brief)
        return GroundingBundle(
            intent=AssistantIntent.UNKNOWN,
            query=query,
            citations=(),
            deterministic_lines=(
                "UNKNOWN: the question cannot be answered from the current grounded copilot contract.",
            ),
            missing=("supported_intent",),
        )

    @staticmethod
    def _market_brief(query: str, brief: CopilotMarketBrief) -> GroundingBundle:
        ranked = sorted(
            (item for item in brief.items if item.status is CopilotStatus.QUALIFIED),
            key=lambda item: item.rank if item.rank is not None else 10_000,
        )
        citations: list[EvidenceCitation] = [
            EvidenceCitation(
                "MARKET:copilot:evaluated",
                "evaluated",
                str(brief.evaluated),
                "copilot",
            ),
            EvidenceCitation(
                "MARKET:copilot:strategy_qualified",
                "strategy_qualified",
                str(brief.strategy_qualified),
                "copilot",
            ),
            EvidenceCitation(
                "MARKET:copilot:context_rejected",
                "context_rejected",
                str(brief.context_rejected),
                "copilot",
            ),
            EvidenceCitation(
                "MARKET:copilot:risk_rejected",
                "risk_rejected",
                str(brief.risk_rejected),
                "copilot",
            ),
            EvidenceCitation(
                "MARKET:copilot:portfolio_rejected",
                "portfolio_rejected",
                str(brief.portfolio_rejected),
                "copilot",
            ),
        ]
        for item in ranked[:10]:
            citations.extend(
                citation
                for citation in _item_citations(item)
                if citation.key in {"status", "rank"}
            )

        lines = [
            f"The current brief evaluated {brief.evaluated} symbols and has "
            f"{len(ranked)} qualified opportunities.",
            (
                f"Context holds/rejections: {brief.context_rejected}; risk rejections: "
                f"{brief.risk_rejected}; portfolio rejections: {brief.portfolio_rejected}."
            ),
        ]
        if ranked:
            lines.append(
                "Qualified ranking: "
                + ", ".join(
                    f"#{item.rank} {item.symbol}" if item.rank is not None else item.symbol
                    for item in ranked[:10]
                )
                + "."
            )
        else:
            lines.append("There are no qualified opportunities in the current brief.")
        return GroundingBundle(
            intent=AssistantIntent.MARKET_BRIEF,
            query=query,
            citations=tuple(citations),
            deterministic_lines=tuple(lines),
        )

    @staticmethod
    def _symbol(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        item = _find_item(brief, symbol)
        if item is None:
            return GroundingBundle(
                intent=AssistantIntent.SYMBOL_EXPLANATION,
                query=query,
                symbol=symbol,
                citations=(),
                deterministic_lines=(
                    "UNKNOWN: no grounded copilot evidence is available for that symbol.",
                ),
                missing=("symbol_evidence",),
            )
        lines = [f"{item.symbol} is currently {item.status.value} in the copilot brief."]
        lines.extend(item.narrative)
        if item.reasons:
            lines.append("Recorded reasons: " + "; ".join(item.reasons) + ".")
        return GroundingBundle(
            intent=AssistantIntent.SYMBOL_EXPLANATION,
            query=query,
            symbol=item.symbol,
            citations=_item_citations(item),
            deterministic_lines=tuple(lines),
        )

    @staticmethod
    def _rejection(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        item = _find_item(brief, symbol)
        if item is None:
            return GroundingBundle(
                intent=AssistantIntent.REJECTION_REASON,
                query=query,
                symbol=symbol,
                citations=(),
                deterministic_lines=("UNKNOWN: no gate evidence is available for that symbol.",),
                missing=("gate_evidence",),
            )
        citations = _item_citations(item)
        lines: tuple[str, ...]
        if item.status is CopilotStatus.QUALIFIED:
            lines = (
                f"{item.symbol} is QUALIFIED in the current brief, so there is no recorded rejection reason.",
            )
        elif item.reasons:
            lines = (
                f"{item.symbol} is {item.status.value}.",
                "Recorded gate reasons: " + "; ".join(item.reasons) + ".",
            )
        else:
            lines = (
                f"{item.symbol} is {item.status.value}, but no more specific gate reason is recorded.",
            )
        return GroundingBundle(
            intent=AssistantIntent.REJECTION_REASON,
            query=query,
            symbol=item.symbol,
            citations=citations,
            deterministic_lines=lines,
        )

    @staticmethod
    def _risk_summary(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        items = [
            item
            for item in brief.items
            if symbol is None or item.symbol.upper() == symbol.upper()
        ]
        risk_citations: list[EvidenceCitation] = []
        for item in items:
            for citation in _item_citations(item):
                key = citation.key.lower()
                if "risk" in key or "capital" in key or "exposure" in key:
                    risk_citations.append(citation)
        if not risk_citations:
            target = symbol or "the current brief"
            return GroundingBundle(
                intent=AssistantIntent.RISK_SUMMARY,
                query=query,
                symbol=symbol,
                citations=(),
                deterministic_lines=(
                    f"UNKNOWN: no grounded risk facts are available for {target}.",
                ),
                missing=("risk_evidence",),
            )
        if symbol is not None:
            lines = (
                f"Grounded risk facts for {symbol.upper()} are listed in the cited evidence.",
            )
        else:
            symbols = sorted({item.symbol for item in items})
            lines = (
                "Grounded risk facts are available for: " + ", ".join(symbols) + ".",
            )
        return GroundingBundle(
            intent=AssistantIntent.RISK_SUMMARY,
            query=query,
            symbol=symbol.upper() if symbol is not None else None,
            citations=tuple(risk_citations),
            deterministic_lines=lines,
        )
