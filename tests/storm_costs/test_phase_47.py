from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.data.providers.http import ProviderError
from app.storm_costs import StormCostService, TonFeeEvidence, parse_market_cost_snapshot


def market(**overrides):
    settings = {"fee": "1200000", "executionFee": "200000", "rolloverFee": "300000000", "fundingPeriod": 3600, "maxPriceImpact": "2400000", "maxPriceSpread": "4800000", "liquidationFeeRatio": "10000000"}
    settings.update(overrides)
    return {"address": "0:market", "config": {"ticker": "TON/USDT"}, "settings": settings, "amm": {"blockTimestamp": "2026-09-12T10:24:22Z", "longFundingRate": "18000", "shortFundingRate": "18000", "vpiSpread": "0"}}


def test_snapshot_normalizes_values_and_preserves_raw_evidence():
    item = parse_market_cost_snapshot(market())
    assert item.protocol_fee_ratio.value == Decimal("0.0012")
    assert item.protocol_fee_ratio.raw == "1200000"
    assert item.execution_fee_ton.value == Decimal("0.0002")
    assert item.funding_period_seconds == 3600
    assert item.observed_at == datetime(2026, 9, 12, 10, 24, 22, tzinfo=timezone.utc)


def test_open_and_close_fee_use_their_current_notional():
    item = parse_market_cost_snapshot(market())
    assert StormCostService.protocol_fee(item, Decimal("1000")) == Decimal("1.2000")
    assert StormCostService.protocol_fee(item, Decimal("1100")) == Decimal("1.3200")


def test_hourly_funding_is_signed_by_direction():
    item = parse_market_cost_snapshot(market())
    long_cost = StormCostService.funding_cost(item, direction="LONG", notional=Decimal("100000"), held_seconds=7200)
    short_cost = StormCostService.funding_cost(item, direction="SHORT", notional=Decimal("100000"), held_seconds=7200)
    assert long_cost == Decimal("3.600000")
    assert short_cost == Decimal("-3.600000")


def test_negative_funding_reverses_payer_and_receiver():
    record = market()
    record["amm"]["longFundingRate"] = "-18000"
    record["amm"]["shortFundingRate"] = "-18000"
    item = parse_market_cost_snapshot(record)
    assert StormCostService.funding_cost(item, direction="LONG", notional=Decimal("100000"), held_seconds=3600) == Decimal("-1.800000")
    assert StormCostService.funding_cost(item, direction="SHORT", notional=Decimal("100000"), held_seconds=3600) == Decimal("1.800000")


def test_missing_fee_remains_unknown_and_fails_closed():
    item = parse_market_cost_snapshot(market(fee=None))
    assert item.protocol_fee_ratio.value is None
    with pytest.raises(ProviderError, match="UNKNOWN"):
        StormCostService.protocol_fee(item, Decimal("100"))


def test_network_fee_prefers_on_chain_settlement():
    pending = TonFeeEvidence(estimated_ton=Decimal("0.08"), reserved_ton=Decimal("0.25"), refunded_ton=Decimal("0.17"))
    assert pending.effective_ton == Decimal("0.08")
    assert not pending.reconciled
    settled = TonFeeEvidence(estimated_ton=Decimal("0.08"), settled_ton=Decimal("0.079"), transaction_hash="abc")
    assert settled.effective_ton == Decimal("0.079")
    assert settled.reconciled


def test_closing_estimate_can_disable_spread():
    record = market()
    record["amm"]["vpiSpread"] = "150000"
    item = parse_market_cost_snapshot(record)
    result = StormCostService.estimate(item, direction="LONG", notional=Decimal("1000"), held_seconds=3600, apply_entry_spread=False)
    assert result.spread_cost is None


def test_invalid_market_record_is_rejected():
    with pytest.raises(ProviderError, match="symbol or market address"):
        parse_market_cost_snapshot({})
