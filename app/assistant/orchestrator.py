from __future__ import annotations

from collections.abc import Callable, Iterable

from app.copilot.models import CopilotMarketBrief

from .analytics import AssistantAnalyticsService
from .grounding import GroundingBuilder
from .model import GroundedLanguageModel, ModelPrompt, ModelReply
from .models import AnswerMode, AssistantIntent, AssistantResponse, GroundingBundle
from .router import AssistantIntentRouter
from .session import InMemoryConversationStore, SessionTurn


SYSTEM_INSTRUCTIONS = """You are a narration layer over deterministic trading evidence.
Use only the supplied evidence. Every market/trading factual claim must be backed by one or more
supplied citation IDs and visible in the answer as [citation_id]. If evidence is insufficient,
say UNKNOWN. Do not invent prices, scores, probabilities, news, position state, journal results,
market changes, risk state, portfolio state, or provider state. What-if evidence is hypothetical
analytics only and must never be presented as a prediction or trade instruction. Do not recommend
or instruct order placement, leverage changes, position sizing, entries, exits, stop changes, or
live activation. You have no execution authority."""

_FORBIDDEN_EXECUTION_PHRASES = (
    "buy now",
    "sell now",
    "place an order",
    "execute an order",
    "execute the trade",
    "open a position",
    "close the position",
    "move the stop",
    "change the stop",
    "increase leverage",
    "set leverage",
    "go long",
    "go short",
)

_COPILOT_INTENTS = frozenset(
    {
        AssistantIntent.MARKET_BRIEF,
        AssistantIntent.SYMBOL_EXPLANATION,
        AssistantIntent.REJECTION_REASON,
        AssistantIntent.RISK_SUMMARY,
    }
)


def _empty_brief() -> CopilotMarketBrief:
    return CopilotMarketBrief(
        evaluated=0,
        strategy_qualified=0,
        context_rejected=0,
        risk_rejected=0,
        portfolio_rejected=0,
        items=(),
    )


class AssistantOrchestrator:
    """Grounded conversation coordinator above read-only copilot and analytics contracts."""

    def __init__(
        self,
        brief_provider: Callable[[], CopilotMarketBrief],
        *,
        model: GroundedLanguageModel | None = None,
        router: AssistantIntentRouter | None = None,
        grounding: GroundingBuilder | None = None,
        analytics: AssistantAnalyticsService | None = None,
        symbols_provider: Callable[[], Iterable[str]] | None = None,
        sessions: InMemoryConversationStore | None = None,
        max_query_chars: int = 2000,
    ) -> None:
        if max_query_chars < 1:
            raise ValueError("max_query_chars must be positive")
        self._brief_provider = brief_provider
        self._model = model
        self._router = router or AssistantIntentRouter()
        self._grounding = grounding or GroundingBuilder(analytics)
        self._symbols_provider = symbols_provider
        self._sessions = sessions or InMemoryConversationStore()
        self._max_query_chars = max_query_chars

    def ask(self, query: str, *, session_id: str | None = None) -> AssistantResponse:
        normalized_query = " ".join(query.strip().split())
        if not normalized_query:
            raise ValueError("assistant query must not be empty")
        if len(normalized_query) > self._max_query_chars:
            raise ValueError(f"assistant query exceeds {self._max_query_chars} characters")

        normalized_session = self._sessions.normalize_session_id(session_id)
        brief: CopilotMarketBrief | None = None
        if self._symbols_provider is None:
            brief = self._brief_provider()
            symbols = tuple(item.symbol for item in brief.items)
        else:
            symbols = tuple(self._symbols_provider())
        last_symbol = self._sessions.last_symbol(normalized_session)
        route = self._router.route(normalized_query, symbols, last_symbol=last_symbol)
        if brief is None:
            brief = self._brief_provider() if route.intent in _COPILOT_INTENTS else _empty_brief()
        bundle = self._grounding.build(route, normalized_query, brief)
        history = tuple(turn.query for turn in self._sessions.history(normalized_session))

        response = self._answer(bundle, history)
        self._sessions.append(
            normalized_session,
            SessionTurn(query=normalized_query, intent=route.intent, symbol=route.symbol),
        )
        return response

    def _answer(self, bundle: GroundingBundle, history: tuple[str, ...]) -> AssistantResponse:
        if self._model is not None and bundle.citations:
            try:
                reply = self._model.generate(
                    ModelPrompt(
                        query=bundle.query,
                        intent=bundle.intent,
                        system_instructions=SYSTEM_INSTRUCTIONS,
                        evidence=bundle.citations,
                        history=history,
                        symbol=bundle.symbol,
                    )
                )
            except Exception:
                return self._deterministic_response(bundle, extra_unknown="model_error")
            if self._valid_model_reply(reply, bundle):
                citation_map = {item.citation_id: item for item in bundle.citations}
                used = tuple(citation_map[citation_id] for citation_id in reply.citations)
                return AssistantResponse(
                    intent=bundle.intent,
                    text=reply.text.strip(),
                    citations=used,
                    mode=AnswerMode.MODEL,
                    symbol=bundle.symbol,
                    grounded=True,
                    unknowns=bundle.missing,
                    model_used=True,
                )
            return self._deterministic_response(bundle, extra_unknown="model_output_rejected")
        return self._deterministic_response(bundle)

    @staticmethod
    def _valid_model_reply(reply: ModelReply, bundle: GroundingBundle) -> bool:
        text = reply.text.strip()
        if not text or not reply.citations:
            return False
        lowered = text.lower()
        if any(phrase in lowered for phrase in _FORBIDDEN_EXECUTION_PHRASES):
            return False
        allowed = {item.citation_id for item in bundle.citations}
        if any(citation_id not in allowed for citation_id in reply.citations):
            return False
        if len(set(reply.citations)) != len(reply.citations):
            return False
        return all(f"[{citation_id}]" in text for citation_id in reply.citations)

    @staticmethod
    def _deterministic_response(
        bundle: GroundingBundle,
        *,
        extra_unknown: str | None = None,
    ) -> AssistantResponse:
        unknowns = list(bundle.missing)
        if extra_unknown is not None:
            unknowns.append(extra_unknown)
        if bundle.intent is AssistantIntent.UNKNOWN or bundle.missing:
            mode = AnswerMode.UNKNOWN if not bundle.citations else AnswerMode.DETERMINISTIC
        else:
            mode = AnswerMode.DETERMINISTIC
        return AssistantResponse(
            intent=bundle.intent,
            text=" ".join(bundle.deterministic_lines),
            citations=bundle.citations,
            mode=mode,
            symbol=bundle.symbol,
            grounded=bool(bundle.citations) or bundle.intent is AssistantIntent.HELP,
            unknowns=tuple(unknowns),
            model_used=False,
        )
