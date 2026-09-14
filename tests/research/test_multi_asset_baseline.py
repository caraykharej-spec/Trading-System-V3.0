from __future__ import annotations

from copy import deepcopy

import pytest

from app.research.multi_asset_baseline import aggregate_multi_asset_baselines


def _report(
    symbol: str,
    *,
    dataset_fp: str,
    evidence_fp: str,
    trades: int,
    total_return: str,
) -> dict[str, object]:
    return {
        "run_type": "LOCKED_HISTORICAL_BASELINE",
        "mode": "RESEARCH_PAPER_ONLY",
        "symbol": symbol,
        "dataset_bundle_fingerprint": dataset_fp,
        "dataset_manifest_fingerprint": f"manifest-{symbol}",
        "dataset_source_shards_fingerprint": f"shards-{symbol}",
        "evidence_fingerprint": evidence_fp,
        "strategy_fingerprint": "strategy-1",
        "config_fingerprint": f"config-{symbol}",
        "dataset_code_revision": "code-1",
        "backtest_code_revision": "code-1",
        "dataset_requested_start": "2025-02-25T00:00:00+00:00",
        "dataset_requested_end": "2026-09-13T00:00:00+00:00",
        "evaluation_start": "2025-09-13T00:00:00+00:00",
        "evaluation_end": "2026-09-13T00:00:00+00:00",
        "warmup_completed_daily_candles": 200,
        "result": {
            "trade_count": trades,
            "rejected_signals": 100,
            "total_return_percent": total_return,
            "max_drawdown_percent": "5.0",
            "win_rate_percent": "40.0",
            "profit_factor": "1.0",
        },
    }


def _reports() -> list[dict[str, object]]:
    return [
        _report(
            "ETH/USDT",
            dataset_fp="dataset-eth",
            evidence_fp="evidence-eth",
            trades=12,
            total_return="1.25",
        ),
        _report(
            "SOL/USDT",
            dataset_fp="dataset-sol",
            evidence_fp="evidence-sol",
            trades=18,
            total_return="-0.50",
        ),
    ]


def test_aggregate_is_deterministic_and_order_independent() -> None:
    forward = aggregate_multi_asset_baselines(_reports())
    reverse = aggregate_multi_asset_baselines(reversed(_reports()))

    assert forward == reverse
    assert forward["symbols"] == ["ETH/USDT", "SOL/USDT"]
    assert forward["total_trade_count"] == 30
    assert forward["total_rejected_signals"] == 200
    assert forward["profitable_asset_count"] == 1
    assert len(str(forward["aggregate_fingerprint"])) == 64


def test_rejects_duplicate_symbol() -> None:
    reports = _reports()
    reports[1]["symbol"] = "ETH/USDT"
    with pytest.raises(ValueError, match="duplicate baseline symbol"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_mismatched_evaluation_window() -> None:
    reports = _reports()
    reports[1]["evaluation_start"] = "2025-09-14T00:00:00+00:00"
    with pytest.raises(ValueError, match="evaluation_start"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_strategy_fingerprint_mismatch() -> None:
    reports = _reports()
    reports[1]["strategy_fingerprint"] = "strategy-2"
    with pytest.raises(ValueError, match="strategy_fingerprint"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_code_revision_mismatch() -> None:
    reports = _reports()
    reports[1]["backtest_code_revision"] = "code-2"
    with pytest.raises(ValueError, match="backtest_code_revision"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_duplicate_dataset_or_evidence_fingerprint() -> None:
    reports = _reports()
    reports[1]["dataset_bundle_fingerprint"] = reports[0]["dataset_bundle_fingerprint"]
    with pytest.raises(ValueError, match="duplicate dataset fingerprint"):
        aggregate_multi_asset_baselines(reports)

    reports = _reports()
    reports[1]["evidence_fingerprint"] = reports[0]["evidence_fingerprint"]
    with pytest.raises(ValueError, match="duplicate evidence fingerprint"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_insufficient_warmup() -> None:
    reports = _reports()
    reports[0]["warmup_completed_daily_candles"] = 199
    with pytest.raises(ValueError, match="warm-up is insufficient"):
        aggregate_multi_asset_baselines(reports)


def test_rejects_missing_total_return() -> None:
    reports = _reports()
    result = reports[0]["result"]
    assert isinstance(result, dict)
    result["total_return_percent"] = None
    with pytest.raises(ValueError, match="total_return_percent missing or invalid"):
        aggregate_multi_asset_baselines(reports)


def test_does_not_require_equal_cost_config_fingerprints() -> None:
    reports = deepcopy(_reports())
    reports[0]["config_fingerprint"] = "eth-cost-config"
    reports[1]["config_fingerprint"] = "sol-cost-config"
    result = aggregate_multi_asset_baselines(reports)
    assert result["asset_count"] == 2
