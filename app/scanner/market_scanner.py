from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    score: float
    state: str


class MarketScanner:
    """First production scanner layer.

    Converts validated market inputs into ranked opportunities.
    Strategy decisions remain outside this layer.
    """

    def scan(self, markets: Iterable[dict]) -> List[ScanResult]:
        results = []
        for item in markets:
            score = float(item.get("score", 0.0))
            results.append(
                ScanResult(
                    symbol=item.get("symbol", "UNKNOWN"),
                    score=score,
                    state="WATCH" if score < 70 else "OPPORTUNITY",
                )
            )
        return sorted(results, key=lambda x: x.score, reverse=True)
