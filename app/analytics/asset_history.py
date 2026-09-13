from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import sqlite3

from app.application.opportunity_pipeline import OpportunityPipelineResult
from app.analytics.performance import PerformanceReport, analyze_performance
from app.journal.repository import JournalRepository


@dataclass(frozen=True)
class AssetJournalStatistics:
    symbol: str
    evaluated_count: int
    top_10_count: int
    top_10_rate_percent: Decimal
    average_score: Decimal | None
    best_score: Decimal | None
    positions_opened: int
    performance: PerformanceReport


class SQLiteMarketEvaluationRepository:
    """Append-only ranking history used for asset-level decision analytics."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save_result(
        self,
        cycle_id: str,
        evaluated_at: datetime,
        result: OpportunityPipelineResult,
    ) -> None:
        for item in result.all_evaluations:
            self.connection.execute(
                """INSERT OR IGNORE INTO market_evaluation_history (
                    cycle_id, symbol, evaluated_at, status, gate_stage, rank,
                    is_top_10, score, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cycle_id,
                    item.symbol,
                    evaluated_at.isoformat(),
                    item.status,
                    item.gate_stage,
                    item.rank,
                    int(item.is_top_10),
                    str(item.score) if item.score is not None else None,
                    str(item.confidence) if item.confidence is not None else None,
                ),
            )
        self.connection.commit()

    def statistics(
        self, journal: JournalRepository
    ) -> tuple[AssetJournalStatistics, ...]:
        rows = self.connection.execute(
            """SELECT symbol, COUNT(*), SUM(is_top_10), AVG(CAST(score AS REAL)),
                      MAX(CAST(score AS REAL))
               FROM market_evaluation_history
               GROUP BY symbol ORDER BY symbol"""
        ).fetchall()
        output: list[AssetJournalStatistics] = []
        for symbol, evaluated, top_10, average_score, best_score in rows:
            trades = journal.list_all(symbol=str(symbol))
            position_row = self.connection.execute(
                "SELECT COUNT(*) FROM positions WHERE symbol = ?", (str(symbol),)
            ).fetchone()
            positions_opened = int(position_row[0]) if position_row is not None else 0
            evaluated_count = int(evaluated)
            top_10_count = int(top_10 or 0)
            output.append(
                AssetJournalStatistics(
                    symbol=str(symbol),
                    evaluated_count=evaluated_count,
                    top_10_count=top_10_count,
                    top_10_rate_percent=(
                        Decimal(top_10_count) / Decimal(evaluated_count) * Decimal("100")
                    ),
                    average_score=(
                        Decimal(str(average_score)) if average_score is not None else None
                    ),
                    best_score=Decimal(str(best_score)) if best_score is not None else None,
                    positions_opened=positions_opened,
                    performance=analyze_performance(trades),
                )
            )
        return tuple(output)
