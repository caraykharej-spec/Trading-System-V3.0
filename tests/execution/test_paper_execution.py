from app.execution.execution_models import ExecutionRequest, OrderSide, ExecutionStatus
from app.execution.paper_engine import PaperExecutionEngine


def test_paper_execution_fill():
    engine = PaperExecutionEngine()
    result = engine.submit(
        ExecutionRequest(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=1,
        )
    )

    assert result.status == ExecutionStatus.FILLED


def test_paper_execution_rejects_invalid_quantity():
    engine = PaperExecutionEngine()
    result = engine.submit(
        ExecutionRequest(
            symbol="BTC",
            side=OrderSide.BUY,
            quantity=0,
        )
    )

    assert result.status == ExecutionStatus.REJECTED
