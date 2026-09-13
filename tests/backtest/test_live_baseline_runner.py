from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.baseline_runner import BaselineRunPolicy, run_live_baseline
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.storm_costs import StormCostService, parse_market_cost_snapshot

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


class FakeProvider(MarketDataProvider):
    name = "gateio-test"

    def get_live_price(self, symbol: str) -> LivePrice:
        return LivePrice(symbol, Decimal("100"), NOW, self.name)

    def get_candles(self, request: MarketDataRequest) -> list[Candle]:
        assert request.timeframe is not None
        step = timedelta(minutes=MINUTES[request.timeframe])
        start = NOW - step * 60
        rows = []
        for index in range(61):
            timestamp = start + step * index
            price = Decimal("100") + Decimal(index) / Decimal("10")
            rows.append(
                Candle(
                    request.symbol,
                    request.timeframe,
                    timestamp,
                    price,
                    price + Decimal("1"),
                    price - Decimal("1"),
                    price + Decimal("0.2"),
                    Decimal("1000"),
                )
            )
        return rows


class FakeCostService(StormCostService):
    def snapshot_for(self, symbol: str):  # type: ignore[no-untyped-def]
        return parse_market_cost_snapshot(
            {
                "address": "0:btc",
                "config": {
                    "ticker": symbol,
                    "type": "base",
                    "settlementToken": "USDT",
                },
                "settings": {
                    "fee": "1200000",
                    "executionFee": "200000",
                    "rolloverFee": "300000000",
                    "fundingPeriod": 3600,
                    "maxPriceImpact": "2400000",
                    "maxPriceSpread": "4800000",
                    "liquidationFeeRatio": "10000000",
                },
                "amm": {
                    "blockTimestamp": "2026-09-13T12:00:00Z",
                    "longFundingRate": "18000",
                    "shortFundingRate": "18000",
                    "vpiSpread": "150000",
                },
            }
        )


def test_live_baseline_seals_realistic_dataset_and_cost_evidence():
    report = run_live_baseline(
        symbol="BTC/USDT",
        policy=BaselineRunPolicy(candle_limit=61, minimum_candles_per_timeframe=50),
        candle_provider=FakeProvider(),
        cost_service=FakeCostService(),
        observed_at=NOW,
        code_revision="a" * 40,
    )

    manifests = report["dataset_manifests"]
    assert isinstance(manifests, dict)
    assert set(manifests) == {"15m", "1h", "4h", "1d"}
    assert all(item["candle_count"] == 60 for item in manifests.values())
    assert len(str(report["dataset_bundle_fingerprint"])) == 64
    assert len(str(report["evidence_fingerprint"])) == 64

    config = report["backtest_config"]
    assert isinstance(config, dict)
    assert config["commission_percent"] == "0.1200"
    assert config["spread_percent"] == "0.01500"
    assert config["slippage_percent"] == "0"
    assert config["funding_rate_percent_per_day"] == "0"

    costs = report["cost_evidence"]
    assert isinstance(costs, dict)
    assert "NOT_CALIBRATED" in str(costs["slippage_status"])
    assert "NO_HISTORICAL_FUNDING_BACKFILL" in str(costs["funding_status"])


def test_same_dataset_strategy_and_costs_have_same_evidence_fingerprint():
    kwargs = {
        "symbol": "BTC/USDT",
        "policy": BaselineRunPolicy(candle_limit=61, minimum_candles_per_timeframe=50),
        "candle_provider": FakeProvider(),
        "cost_service": FakeCostService(),
        "observed_at": NOW,
        "code_revision": "b" * 40,
    }
    first = run_live_baseline(**kwargs)
    second = run_live_baseline(**kwargs)

    assert first["dataset_bundle_fingerprint"] == second["dataset_bundle_fingerprint"]
    assert first["strategy_fingerprint"] == second["strategy_fingerprint"]
    assert first["config_fingerprint"] == second["config_fingerprint"]
    assert first["evidence_fingerprint"] == second["evidence_fingerprint"]
