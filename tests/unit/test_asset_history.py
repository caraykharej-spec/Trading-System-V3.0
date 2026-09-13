from datetime import datetime, timezone
from decimal import Decimal

from app.analytics.asset_history import SQLiteMarketEvaluationRepository
from app.application.opportunity_pipeline import MarketEvaluation, OpportunityPipelineResult
from app.journal.sqlite_repository import SQLiteJournalRepository
from app.storage.database import connect


def result(*items: MarketEvaluation) -> OpportunityPipelineResult:
    return OpportunityPipelineResult(2, 1, 0, 0, 0, (), all_evaluations=items)


def test_asset_history_counts_top_ten_and_average_score(tmp_path):
    connection = connect(tmp_path / "history.db")
    repository = SQLiteMarketEvaluationRepository(connection)
    observed = datetime(2026, 9, 12, tzinfo=timezone.utc)
    repository.save_result(
        "c1",
        observed,
        result(
            MarketEvaluation("BTC/USDT", "QUALIFIED", "COMPLETE", 1, True, score=Decimal("95")),
            MarketEvaluation("ETH/USDT", "NO_TRADE", "STRATEGY"),
        ),
    )
    repository.save_result(
        "c2",
        observed,
        result(
            MarketEvaluation("BTC/USDT", "QUALIFIED", "COMPLETE", 12, False, score=Decimal("85")),
            MarketEvaluation("ETH/USDT", "NO_TRADE", "STRATEGY"),
        ),
    )

    stats = repository.statistics(SQLiteJournalRepository(connection))
    btc = next(item for item in stats if item.symbol == "BTC/USDT")
    assert btc.evaluated_count == 2
    assert btc.top_10_count == 1
    assert btc.top_10_rate_percent == Decimal("50.0")
    assert btc.average_score == Decimal("90.0")
    assert btc.positions_opened == 0


def test_cycle_replay_does_not_double_count_market_history(tmp_path):
    connection = connect(tmp_path / "history.db")
    repository = SQLiteMarketEvaluationRepository(connection)
    observed = datetime(2026, 9, 12, tzinfo=timezone.utc)
    payload = result(MarketEvaluation("BTC/USDT", "QUALIFIED", "COMPLETE", 1, True, score=Decimal("90")))
    repository.save_result("same", observed, payload)
    repository.save_result("same", observed, payload)
    stats = repository.statistics(SQLiteJournalRepository(connection))
    assert stats[0].evaluated_count == 1
