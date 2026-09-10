from dataclasses import dataclass


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    rank: int
    score: float
    confidence: str


class OpportunityEngine:
    """Ranks scanner output for downstream strategy modules."""

    def rank(self, scan_results):
        ranked = []
        for index, result in enumerate(scan_results, start=1):
            ranked.append(
                Opportunity(
                    symbol=result.symbol,
                    rank=index,
                    score=result.score,
                    confidence="HIGH" if result.score >= 80 else "MEDIUM",
                )
            )
        return ranked
