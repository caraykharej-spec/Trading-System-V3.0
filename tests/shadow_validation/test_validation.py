from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.application.opportunity_pipeline import RiskContext
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.http import ProviderError
from app.portfolio.account import Account
from app.shadow_validation.validation import ShadowValidator, TIMEFRAMES
from app.shadow_validation.venue import TimestampedStormProvider
from app.universe.config_loader import load_universe

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


@dataclass
class FixtureProvider:
    name: str
    broken: bool = False
    stale: bool = False
    wrong_symbol: bool = False
    calls: int = 0

    def get_live_price(self, symbol):
        self.calls += 1
        if self.broken:
            raise ProviderError("unavailable")
        return LivePrice(symbol, Decimal("100"),
                         NOW - timedelta(hours=1) if self.stale else NOW, self.name)

    def get_candles(self, request: MarketDataRequest):
        self.calls += 1
        if self.broken:
            raise ProviderError("unavailable")
        seconds = {"1d": 86400, "4h": 14400, "1h": 3600, "15m": 900}[request.timeframe]
        return [Candle("WRONG" if self.wrong_symbol else request.symbol, request.timeframe,
                       NOW - timedelta(seconds=seconds * i),
                       Decimal("100"), Decimal("101"), Decimal("99"),
                       Decimal("100"), Decimal("10")) for i in range(260, -1, -1)]


def risk_context(symbol):
    registry, _, contracts = load_universe("config/universe.json")
    return RiskContext(Account(Decimal("10000")), [], registry.get(symbol),
                       contracts[symbol], Decimal("1"), provider="STORM")


def validator(storm=None, gate=None, yahoo=None):
    return ShadowValidator(storm or FixtureProvider("storm"),
                           (gate or FixtureProvider("gateio"), yahoo or FixtureProvider("yahoo")),
                           risk_context, clock=lambda: NOW)


def test_capture_closed_candles_and_real_pipeline_replay_without_additional_network():
    storm, gate, yahoo = [FixtureProvider(n) for n in ("storm", "gateio", "yahoo")]
    report = validator(storm, gate, yahoo).run(("BTC/USDT",))
    assert report.status == "PASS"
    assert report.execution_enabled is False
    assert report.decisions["evaluated"] == 1
    assert report.decisions["rejections"]  # No-trade is a valid integration result.
    assert (storm.calls, gate.calls, yahoo.calls) == (1, len(TIMEFRAMES), 0)
    assert len(report.data_digest) == len(report.decision_digest) == 64
    assert report.data_digest == validator().run(("BTC/USDT",)).data_digest


def test_fallback_provenance_is_recorded():
    report = validator(gate=FixtureProvider("gateio", broken=True)).run(("BTC/USDT",))
    assert report.status == "PASS"
    rows = [c for c in report.checks if "timeframe" in c]
    assert all(c["provider"] == "yahoo" and c["fallback_reasons"] for c in rows)


@pytest.mark.parametrize("provider", [FixtureProvider("storm", broken=True),
                                      FixtureProvider("storm", stale=True)])
def test_unavailable_or_stale_storm_holds_without_decisions(provider):
    report = validator(storm=provider).run(("BTC/USDT",))
    assert report.status == "HOLD"
    assert report.decisions is None


def test_mixed_symbol_candles_cannot_pass():
    report = validator(gate=FixtureProvider("gateio", wrong_symbol=True),
                       yahoo=FixtureProvider("yahoo", broken=True)).run(("BTC/USDT",))
    assert report.status == "HOLD"
    assert report.decision_digest is None


@pytest.mark.parametrize("symbols", [(), ("BTC/USDT", "BTC/USDT"), tuple(map(str, range(11)))])
def test_bounded_nonempty_unique_universe(symbols):
    with pytest.raises(ValueError):
        validator().run(symbols)


def test_source_policy_is_enforced():
    with pytest.raises(ValueError):
        validator(storm=FixtureProvider("gateio"))
    with pytest.raises(ValueError):
        validator(gate=FixtureProvider("yahoo"))


def test_missing_storm_source_timestamp_is_not_replaced_with_now(monkeypatch):
    monkeypatch.setattr(TimestampedStormProvider, "list_market_records",
                        lambda self: ({"symbol": "BTC", "price": "100"},))
    with pytest.raises(ProviderError, match="timestamp"):
        TimestampedStormProvider().get_live_price("BTC")


def test_future_candles_hold(monkeypatch):
    original = FixtureProvider.get_candles

    def future(self, request):
        items = original(self, request)
        items[-1] = replace(items[-1], timestamp=NOW + timedelta(days=1))
        return items

    monkeypatch.setattr(FixtureProvider, "get_candles", future)
    assert validator().run(("BTC/USDT",)).status == "HOLD"


def test_pipeline_exception_is_fail_not_pass():
    instance = validator()
    # A malformed immutable capture must not silently pass the analysis stage.
    from unittest.mock import patch
    with patch("app.shadow_validation.validation.analyze_market", side_effect=RuntimeError):
        report = instance.run(("BTC/USDT",))
    assert report.status == "FAIL"
    assert report.decisions is None


def bullish_snapshot(symbol, timeframe, candles):
    from app.market.analysis import MarketSnapshot
    from app.market.indicators import IndicatorSnapshot
    from app.market.liquidity import LiquidityResult
    from app.market.regime import RegimeResult
    from app.market.structure import StructureResult
    from app.market.trend import TrendResult
    d = Decimal
    indicators = IndicatorSnapshot(d("100"), d("99"), d("95"), d("55"), d("2"), d("100"))
    return MarketSnapshot(
        symbol, timeframe, indicators, TrendResult("BULLISH", "STRONG", d("100"), indicators),
        StructureResult("BREAKOUT_UP", d("98"), d("102"), d("100")),
        RegimeResult("TRENDING_BULL", "NORMAL", d("100")),
        LiquidityResult(d("100"), d("100"), d("1"), d("100")), d("100"),
    )


def test_qualified_signal_runs_real_risk_and_portfolio_gates(monkeypatch):
    monkeypatch.setattr("app.shadow_validation.validation.analyze_market", bullish_snapshot)
    report = validator().run(("BTC/USDT",))
    assert report.status == "PASS"
    assert len(report.decisions["qualified"]) == 1
    assert report.decisions["qualified"][0]["risk"]["approved"]
    assert report.decisions["qualified"][0]["portfolio"]["approved"]


def test_risk_rejection_remains_rejected_and_replay_detects_drift(monkeypatch):
    monkeypatch.setattr("app.shadow_validation.validation.analyze_market", bullish_snapshot)
    instance = validator()
    instance.risk_context_loader = lambda s: replace(risk_context(s), leverage=Decimal("7"))
    rejected = instance.run(("BTC/USDT",))
    assert rejected.status == "PASS"
    assert rejected.decisions["risk_rejected"] == 1
    assert rejected.decisions["qualified"] == ()
    contexts = iter([risk_context("BTC/USDT"),
                     replace(risk_context("BTC/USDT"), leverage=Decimal("7"))])
    instance.risk_context_loader = lambda s: next(contexts)
    assert instance.run(("BTC/USDT",)).status == "FAIL"
