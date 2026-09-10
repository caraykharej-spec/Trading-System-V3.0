from app.data.production import DataProductionService


def test_data_production_normalizes_candles():
    service = DataProductionService()

    batch = service.build_batch(
        "BTC",
        "15m",
        [
            {
                "open": "100",
                "high": "110",
                "low": "90",
                "close": "105",
                "volume": "50",
            }
        ],
    )

    assert batch.symbol == "BTC"
    assert batch.candles[0]["close"] == 105
