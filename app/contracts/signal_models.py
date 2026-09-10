from dataclasses import dataclass


@dataclass(frozen=True)
class SignalContract:
    symbol: str
    strategy: str
    direction: str
    score: float
    confidence: float
    reason: str
