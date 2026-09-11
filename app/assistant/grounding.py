from __future__ import annotations

from app.copilot.models import CopilotItemBrief, CopilotMarketBrief, CopilotStatus

from .analytics import AssistantAnalyticsService
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

    def __init__(self, analytics: AssistantAnalyticsService | None = None) -> None:
        self._analytics = analytics

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
                    "I can explain the current market brief, symbol evidence, risk facts, open positions, journal analytics, market change, or a read-only percentage what-if scenario.",
                    "I cannot submit orders, change positions or risk limits, or activate live trading.",
                ),
            )
        if route.intent is AssistantIntent.POSITIONS:
            return self._positions(query, route.symbol)
        if route.intent is AssistantIntent.JOURNAL:
            return self._journal(query, route.symbol)
        if route.intent is AssistantIntent.MARKET_CHANGE:
            return self._market_change(query, route.symbol)
        if route.intent is AssistantIntent.WHAT_IF:
            return self._what_if(query, route)
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
                "UNKNOWN: the question cannot be answered from the current grounded assistant contract.",
            ),
            missing=("supported_intent",),
        )

    def _analytics_unavailable(
        self, intent: AssistantIntent, query: str, symbol: str | None
    ) -> GroundingBundle:
        return GroundingBundle(
            intent=intent,
            query=query,
            symbol=symbol,
            citations=(),
            deterministic_lines=(
                "UNKNOWN: assistant analytics are not configured for this runtime.",
            ),
            missing=("assistant_analytics",),
        )

    def _positions(self, query: str, symbol: str | None) -> GroundingBundle:
        if self._analytics is None:
            return self._analytics_unavailable(AssistantIntent.POSITIONS, query, symbol)
        snapshot = self._analytics.positions(symbol)
        scope = symbol.upper() if symbol is not None else "POSITIONS"
        citations: list[EvidenceCitation] = [
            EvidenceCitation(
                _citation_id(scope, "position_repository", "open_position_count"),
                "open_position_count",
                str(len(snapshot.items)),
                "position_repository",
                symbol.upper() if symbol is not None else None,
            )
        ]
        for item in snapshot.items:
            prefix = item.position_id
            static = (
                (f"{prefix}_side", item.side),
                (f"{prefix}_entry_price", str(item.entry_price)),
                (f"{prefix}_stop_loss", str(item.stop_loss)),
                (f"{prefix}_take_profit", str(item.take_profit) if item.take_profit is not None else "NONE"),
                (f"{prefix}_total_amount", str(item.total_amount)),
                (f"{prefix}_quantity", str(item.quantity)),
                (f"{prefix}_leverage", str(item.leverage)),
                (f"{prefix}_opened_at", item.opened_at.isoformat()),
            )
            for key, value in static:
                citations.append(
                    EvidenceCitation(
                        _citation_id(item.symbol, "position_repository", key),
                        key,
                        value,
                        "position_repository",
                        item.symbol,
                    )
                )
            if item.current_price is not None:
                citations.append(
                    EvidenceCitation(
                        _citation_id(item.symbol, "live_price", f"{prefix}_current_price"),
                        f"{prefix}_current_price",
                        str(item.current_price),
                        "live_price",
                        item.symbol,
                    )
                )
            if item.unrealized_pnl is not None:
                citations.append(
                    EvidenceCitation(
                        _citation_id(item.symbol, "position_analytics", f"{prefix}_unrealized_pnl"),
                        f"{prefix}_unrealized_pnl",
                        str(item.unrealized_pnl),
                        "position_analytics",
                        item.symbol,
                    )
                )
        if snapshot.total_unrealized_pnl is not None:
            citations.append(
                EvidenceCitation(
                    _citation_id(scope, "position_analytics", "total_unrealized_pnl"),
                    "total_unrealized_pnl",
                    str(snapshot.total_unrealized_pnl),
                    "position_analytics",
                    symbol.upper() if symbol is not None else None,
                )
            )
        if not snapshot.items:
            lines = (f"There are no open positions for {scope}." if symbol else "There are no open positions.",)
        else:
            lines = (
                f"Open positions in scope: {len(snapshot.items)}.",
                "Position state and read-only unrealized P&L are available in the cited evidence.",
            )
        missing = tuple(f"live_price:{item}" for item in snapshot.missing_live_prices)
        return GroundingBundle(
            intent=AssistantIntent.POSITIONS,
            query=query,
            symbol=symbol.upper() if symbol is not None else None,
            citations=tuple(citations),
            deterministic_lines=lines,
            missing=missing,
        )

    def _journal(self, query: str, symbol: str | None) -> GroundingBundle:
        if self._analytics is None:
            return self._analytics_unavailable(AssistantIntent.JOURNAL, query, symbol)
        snapshot = self._analytics.journal(symbol)
        report = snapshot.report
        scope = snapshot.symbol or "JOURNAL"
        metrics = (
            ("total_trades", report.total_trades),
            ("wins", report.wins),
            ("losses", report.losses),
            ("breakeven", report.breakeven),
            ("net_pnl", report.net_pnl),
            ("win_rate_percent", report.win_rate_percent),
            ("average_pnl", report.average_pnl),
            ("expectancy", report.expectancy),
            ("profit_factor", report.profit_factor if report.profit_factor is not None else "NONE"),
            ("average_r_multiple", report.average_r_multiple if report.average_r_multiple is not None else "NONE"),
            ("max_consecutive_losses", report.max_consecutive_losses),
        )
        citations = [
            EvidenceCitation(
                _citation_id(scope, "journal_analytics", key),
                key,
                str(value),
                "journal_analytics",
                snapshot.symbol,
            )
            for key, value in metrics
        ]
        for item in snapshot.recent:
            key_base = item.position_id
            recent_metrics = (
                (f"{key_base}_symbol", item.symbol),
                (f"{key_base}_side", item.side),
                (f"{key_base}_realized_pnl", item.realized_pnl),
                (f"{key_base}_return_percent", item.return_percent),
                (f"{key_base}_realized_r_multiple", item.realized_r_multiple if item.realized_r_multiple is not None else "NONE"),
                (f"{key_base}_close_reason", item.close_reason),
                (f"{key_base}_closed_at", item.closed_at.isoformat()),
            )
            for key, value in recent_metrics:
                citations.append(
                    EvidenceCitation(
                        _citation_id(item.symbol, "journal", key),
                        key,
                        str(value),
                        "journal",
                        item.symbol,
                    )
                )
        target = snapshot.symbol or "all recorded trades"
        lines = (
            f"Journal analytics for {target}: {report.total_trades} trades, net P&L {report.net_pnl}, win rate {report.win_rate_percent}%.",
            f"Recent journal records included: {len(snapshot.recent)}.",
        )
        return GroundingBundle(
            intent=AssistantIntent.JOURNAL,
            query=query,
            symbol=snapshot.symbol,
            citations=tuple(citations),
            deterministic_lines=lines,
        )

    def _market_change(self, query: str, symbol: str | None) -> GroundingBundle:
        if symbol is None:
            return GroundingBundle(
                intent=AssistantIntent.MARKET_CHANGE,
                query=query,
                citations=(),
                deterministic_lines=("UNKNOWN: market-change analysis requires a symbol.",),
                missing=("symbol",),
            )
        if self._analytics is None:
            return self._analytics_unavailable(AssistantIntent.MARKET_CHANGE, query, symbol)
        snapshot = self._analytics.market_change(symbol)
        citations: list[EvidenceCitation] = []
        if snapshot.current_price is not None:
            citations.append(
                EvidenceCitation(
                    _citation_id(snapshot.symbol, "live_price", "current_price"),
                    "current_price",
                    str(snapshot.current_price),
                    "live_price",
                    snapshot.symbol,
                )
            )
        for point in snapshot.points:
            for key, value, source in (
                (f"{point.timeframe}_reference_close", point.reference_close, "market_data"),
                (f"{point.timeframe}_reference_timestamp", point.reference_timestamp.isoformat(), "market_data"),
                (f"{point.timeframe}_change_percent", point.change_percent, "market_change"),
            ):
                citations.append(
                    EvidenceCitation(
                        _citation_id(snapshot.symbol, source, key),
                        key,
                        str(value),
                        source,
                        snapshot.symbol,
                    )
                )
        lines = [f"Market-change evidence for {snapshot.symbol} uses the current live price versus the prior completed candle close for each available timeframe."]
        for point in snapshot.points:
            lines.append(f"{point.timeframe}: {point.change_percent}% from reference close {point.reference_close}.")
        if not snapshot.points:
            lines.append("No comparable timeframe change could be computed from available candles.")
        return GroundingBundle(
            intent=AssistantIntent.MARKET_CHANGE,
            query=query,
            symbol=snapshot.symbol,
            citations=tuple(citations),
            deterministic_lines=tuple(lines),
            missing=snapshot.missing,
        )

    def _what_if(self, query: str, route: IntentRoute) -> GroundingBundle:
        if route.symbol is None:
            return GroundingBundle(
                intent=AssistantIntent.WHAT_IF,
                query=query,
                citations=(),
                deterministic_lines=("UNKNOWN: what-if analysis requires a symbol.",),
                missing=("symbol",),
            )
        if route.scenario_percent is None:
            return GroundingBundle(
                intent=AssistantIntent.WHAT_IF,
                query=query,
                symbol=route.symbol,
                citations=(),
                deterministic_lines=("UNKNOWN: what-if analysis currently requires an explicit percentage change, for example +5% or -5%.",),
                missing=("scenario_percent",),
            )
        if self._analytics is None:
            return self._analytics_unavailable(AssistantIntent.WHAT_IF, query, route.symbol)
        snapshot = self._analytics.what_if(route.symbol, route.scenario_percent)
        citations: list[EvidenceCitation] = [
            EvidenceCitation(
                _citation_id(snapshot.symbol, "what_if", "scenario_percent"),
                "scenario_percent",
                str(snapshot.percent_change),
                "what_if",
                snapshot.symbol,
            )
        ]
        if snapshot.current_price is not None:
            citations.append(
                EvidenceCitation(
                    _citation_id(snapshot.symbol, "live_price", "current_price"),
                    "current_price",
                    str(snapshot.current_price),
                    "live_price",
                    snapshot.symbol,
                )
            )
        if snapshot.hypothetical_price is not None:
            citations.append(
                EvidenceCitation(
                    _citation_id(snapshot.symbol, "what_if", "hypothetical_price"),
                    "hypothetical_price",
                    str(snapshot.hypothetical_price),
                    "what_if",
                    snapshot.symbol,
                )
            )
        for impact in snapshot.impacts:
            for key, value in (
                (f"{impact.position_id}_current_unrealized_pnl", impact.current_unrealized_pnl),
                (f"{impact.position_id}_hypothetical_pnl", impact.hypothetical_pnl),
                (f"{impact.position_id}_pnl_delta", impact.pnl_delta),
            ):
                citations.append(
                    EvidenceCitation(
                        _citation_id(snapshot.symbol, "what_if", key),
                        key,
                        str(value),
                        "what_if",
                        snapshot.symbol,
                    )
                )
        if snapshot.pnl_delta is not None:
            citations.append(
                EvidenceCitation(
                    _citation_id(snapshot.symbol, "what_if", "portfolio_pnl_delta"),
                    "portfolio_pnl_delta",
                    str(snapshot.pnl_delta),
                    "what_if",
                    snapshot.symbol,
                )
            )
        if snapshot.hypothetical_price is None:
            lines = ("UNKNOWN: the hypothetical price cannot be computed because current live price is unavailable.",)
        else:
            lines = (
                f"Hypothetical only: a {snapshot.percent_change}% move from the current price implies {snapshot.hypothetical_price} for {snapshot.symbol}.",
                f"Open positions affected: {len(snapshot.impacts)}. This simulation does not change any position, stop, leverage, risk limit, or order state.",
            )
        return GroundingBundle(
            intent=AssistantIntent.WHAT_IF,
            query=query,
            symbol=snapshot.symbol,
            citations=tuple(citations),
            deterministic_lines=lines,
            missing=snapshot.missing,
        )

    @staticmethod
    def _market_brief(query: str, brief: CopilotMarketBrief) -> GroundingBundle:
        ranked = sorted(
            (item for item in brief.items if item.status is CopilotStatus.QUALIFIED),
            key=lambda item: item.rank if item.rank is not None else 10_000,
        )
        citations: list[EvidenceCitation] = [
            EvidenceCitation("MARKET:copilot:evaluated", "evaluated", str(brief.evaluated), "copilot"),
            EvidenceCitation("MARKET:copilot:strategy_qualified", "strategy_qualified", str(brief.strategy_qualified), "copilot"),
            EvidenceCitation("MARKET:copilot:context_rejected", "context_rejected", str(brief.context_rejected), "copilot"),
            EvidenceCitation("MARKET:copilot:risk_rejected", "risk_rejected", str(brief.risk_rejected), "copilot"),
            EvidenceCitation("MARKET:copilot:portfolio_rejected", "portfolio_rejected", str(brief.portfolio_rejected), "copilot"),
        ]
        for item in ranked[:10]:
            citations.extend(citation for citation in _item_citations(item) if citation.key in {"status", "rank"})
        lines = [
            f"The current brief evaluated {brief.evaluated} symbols and has {len(ranked)} qualified opportunities.",
            f"Context holds/rejections: {brief.context_rejected}; risk rejections: {brief.risk_rejected}; portfolio rejections: {brief.portfolio_rejected}.",
        ]
        if ranked:
            lines.append("Qualified ranking: " + ", ".join(f"#{item.rank} {item.symbol}" if item.rank is not None else item.symbol for item in ranked[:10]) + ".")
        else:
            lines.append("There are no qualified opportunities in the current brief.")
        return GroundingBundle(intent=AssistantIntent.MARKET_BRIEF, query=query, citations=tuple(citations), deterministic_lines=tuple(lines))

    @staticmethod
    def _symbol(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        item = _find_item(brief, symbol)
        if item is None:
            return GroundingBundle(intent=AssistantIntent.SYMBOL_EXPLANATION, query=query, symbol=symbol, citations=(), deterministic_lines=("UNKNOWN: no grounded copilot evidence is available for that symbol.",), missing=("symbol_evidence",))
        lines = [f"{item.symbol} is currently {item.status.value} in the copilot brief."]
        lines.extend(item.narrative)
        if item.reasons:
            lines.append("Recorded reasons: " + "; ".join(item.reasons) + ".")
        return GroundingBundle(intent=AssistantIntent.SYMBOL_EXPLANATION, query=query, symbol=item.symbol, citations=_item_citations(item), deterministic_lines=tuple(lines))

    @staticmethod
    def _rejection(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        item = _find_item(brief, symbol)
        if item is None:
            return GroundingBundle(intent=AssistantIntent.REJECTION_REASON, query=query, symbol=symbol, citations=(), deterministic_lines=("UNKNOWN: no gate evidence is available for that symbol.",), missing=("gate_evidence",))
        citations = _item_citations(item)
        if item.status is CopilotStatus.QUALIFIED:
            lines = (f"{item.symbol} is QUALIFIED in the current brief, so there is no recorded rejection reason.",)
        elif item.reasons:
            lines = (f"{item.symbol} is {item.status.value}.", "Recorded gate reasons: " + "; ".join(item.reasons) + ".")
        else:
            lines = (f"{item.symbol} is {item.status.value}, but no more specific gate reason is recorded.",)
        return GroundingBundle(intent=AssistantIntent.REJECTION_REASON, query=query, symbol=item.symbol, citations=citations, deterministic_lines=lines)

    @staticmethod
    def _risk_summary(query: str, symbol: str | None, brief: CopilotMarketBrief) -> GroundingBundle:
        items = [item for item in brief.items if symbol is None or item.symbol.upper() == symbol.upper()]
        risk_citations: list[EvidenceCitation] = []
        for item in items:
            for citation in _item_citations(item):
                key = citation.key.lower()
                if "risk" in key or "capital" in key or "exposure" in key:
                    risk_citations.append(citation)
        if not risk_citations:
            target = symbol or "the current brief"
            return GroundingBundle(intent=AssistantIntent.RISK_SUMMARY, query=query, symbol=symbol, citations=(), deterministic_lines=(f"UNKNOWN: no grounded risk facts are available for {target}.",), missing=("risk_evidence",))
        if symbol is not None:
            lines = (f"Grounded risk facts for {symbol.upper()} are listed in the cited evidence.",)
        else:
            symbols = sorted({item.symbol for item in items})
            lines = ("Grounded risk facts are available for: " + ", ".join(symbols) + ".",)
        return GroundingBundle(intent=AssistantIntent.RISK_SUMMARY, query=query, symbol=symbol.upper() if symbol is not None else None, citations=tuple(risk_citations), deterministic_lines=lines)
