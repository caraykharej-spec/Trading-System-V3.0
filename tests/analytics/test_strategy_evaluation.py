from app.analytics.strategy_evaluation import StrategyEvaluator


def test_strategy_evaluation():
    evaluator = StrategyEvaluator()
    result = evaluator.evaluate(
        "test_strategy",
        [{"pnl": 100}, {"pnl": -40}, {"pnl": 50}],
    )

    assert result.total_trades == 3
    assert result.total_pnl == 110
    assert result.win_rate == 2 / 3
    assert result.profit_factor == 150 / 40
