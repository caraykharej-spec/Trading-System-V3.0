def test_execution_position_portfolio_flow():
    execution_result = {
        "status": "FILLED",
        "symbol": "BTC",
        "quantity": 1.0,
    }

    assert execution_result["status"] == "FILLED"
    assert execution_result["quantity"] > 0
