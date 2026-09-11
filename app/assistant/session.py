from __future__ import annotations

from dataclasses import dataclass
import re

from .models import AssistantIntent


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class SessionTurn:
    query: str
    intent: AssistantIntent
    symbol: str | None = None


class InMemoryConversationStore:
    """Small bounded in-memory context store.

    It intentionally retains only recent user queries plus routed intent/symbol,
    not model-generated answers or trading state. Fresh market evidence is
    always reloaded from the copilot provider for every request.
    """

    def __init__(self, *, max_turns: int = 6, max_sessions: int = 100) -> None:
        if max_turns < 1 or max_sessions < 1:
            raise ValueError("conversation store limits must be positive")
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        self._sessions: dict[str, list[SessionTurn]] = {}

    @staticmethod
    def normalize_session_id(session_id: str | None) -> str | None:
        if session_id is None:
            return None
        normalized = session_id.strip()
        if not _SESSION_ID_RE.fullmatch(normalized):
            raise ValueError("session_id must be 1-64 characters: letters, numbers, _ or -")
        return normalized

    def history(self, session_id: str | None) -> tuple[SessionTurn, ...]:
        normalized = self.normalize_session_id(session_id)
        if normalized is None:
            return ()
        return tuple(self._sessions.get(normalized, ()))

    def last_symbol(self, session_id: str | None) -> str | None:
        for turn in reversed(self.history(session_id)):
            if turn.symbol is not None:
                return turn.symbol
        return None

    def append(self, session_id: str | None, turn: SessionTurn) -> None:
        normalized = self.normalize_session_id(session_id)
        if normalized is None:
            return
        if normalized not in self._sessions and len(self._sessions) >= self.max_sessions:
            oldest = next(iter(self._sessions))
            del self._sessions[oldest]
        turns = self._sessions.setdefault(normalized, [])
        turns.append(turn)
        if len(turns) > self.max_turns:
            del turns[:-self.max_turns]
