from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import AssistantIntent, EvidenceCitation


@dataclass(frozen=True)
class ModelPrompt:
    query: str
    intent: AssistantIntent
    system_instructions: str
    evidence: tuple[EvidenceCitation, ...]
    history: tuple[str, ...] = ()
    symbol: str | None = None


@dataclass(frozen=True)
class ModelReply:
    text: str
    citations: tuple[str, ...]


class GroundedLanguageModel(Protocol):
    """Provider-neutral model contract for grounded narration only."""

    def generate(self, prompt: ModelPrompt) -> ModelReply:
        ...
