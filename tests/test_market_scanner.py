from app.scanner.market_scanner import MarketScanner


def test_market_scanner_ranking():
    scanner = MarketScanner()
    result = scanner.scan([
        {"symbol": "BTC", "score": 90},
        {"symbol": "ETH", "score": 60},
    ])

    assert result[0].symbol == "BTC"
    assert result[0].state == "OPPORTUNITY"
