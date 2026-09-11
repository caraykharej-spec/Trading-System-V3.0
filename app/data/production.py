"""Production-grade market data preparation layer."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Protocol


class QualityReport(Protocol):
    valid: bool


class QualityChecker(Protocol):
    def validate(self, candles: list[dict[str, Any]]) -> QualityReport: ...


@dataclass(frozen=True)
class DataBatch:
    symbol: str
    timeframe: str
    candles: list[dict[str, Any]]
    created_at: datetime


class DataProductionService:
    """Normalizes and validates market data before strategy consumption."""

    def __init__(self, quality_checker: QualityChecker | None = None) -> None:
        self.quality_checker = quality_checker

    def build_batch(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[dict[str, Any]],
    ) -> DataBatch:
        normalized = [self._normalize(candle) for candle in candles]

        if self.quality_checker is not None:
            report = self.quality_checker.validate(normalized)
            if not report.valid:
                raise ValueError("market data quality validation failed")

        return DataBatch(
            symbol=symbol.upper(),
            timeframe=timeframe,
            candles=normalized,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalize(candle: dict[str, Any]) -> dict[str, Any]:
        required = ("open", "high", "low", "close", "volume")
        missing = [key for key in required if key not in candle]
        if missing:
            raise ValueError(f"missing candle fields: {missing}")

        result = dict(candle)
        for key in required:
            result[key] = Decimal(str(result[key]))
        return result
