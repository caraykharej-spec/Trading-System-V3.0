from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.data.historical_backfill import load_locked_dataset
from app.storm_costs import StormCostService
from app.strategy.rules import DEFAULT_RULES

from .diagnostics import SignalAttritionDiagnostics
from .engine import BacktestEngine
from .models import BacktestConfig, BacktestResult

_REQUIRED_DAILY_WARMUP = 200


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _manifest_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"locked dataset {field} missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"locked dataset {field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _result_payload(result: BacktestResult) -> dict[str, object]:
    trades: list[dict[str, object]] = []
    for index, trade in enumerate(result.trades, start=1):
        trades.append(
            {
                "trade_index": index,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "setup": trade.setup,
                "entry_time": trade.entry_time,
                "entry_price": trade.entry_price,
                "exit_time": trade.exit_time,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "target": trade.target,
                "quantity": trade.quantity,
                "total_amount": trade.total_amount,
                "leverage": trade.leverage,
                "realized_pnl": trade.realized_pnl,
                "commission": trade.commission,
                "funding_cost": trade.funding_cost,
                "exit_reason": trade.exit_reason,
            }
        )
    return {
        "initial_equity": result.initial_equity,
        "final_equity": result.final_equity,
        "trade_count": len(result.trades),
        "rejected_signals": result.rejected_signals,
        "open_positions_at_end": result.open_positions_at_end,
        "max_drawdown_percent": result.max_drawdown_percent,
        "win_rate_percent": result.win_rate_percent,
        "profit_factor": result.profit_factor,
        "total_return_percent": result.total_return_percent,
        "max_concurrent_positions": result.max_concurrent_positions,
        "trades": trades,
    }


def _cost_config(
    service: StormCostService,
    symbol: str,
) -> tuple[BacktestConfig, dict[str, object]]:
    snapshot = service.snapshot_for(symbol)
    service.require_complete(snapshot, ("protocol_fee_ratio", "spread_ratio"))
    protocol_ratio = snapshot.protocol_fee_ratio.value
    spread_ratio = snapshot.spread_ratio.value
    if protocol_ratio is None or spread_ratio is None:
        raise RuntimeError("Storm fee/spread validation returned incomplete evidence")

    config = BacktestConfig(
        commission_percent=protocol_ratio * Decimal("100"),
        spread_percent=spread_ratio * Decimal("100"),
        slippage_percent=Decimal("0"),
        funding_rate_percent_per_day=Decimal("0"),
    )
    evidence: dict[str, object] = {
        "storm_market_address": snapshot.market_address,
        "storm_observed_at": snapshot.observed_at,
        "commission_percent": config.commission_percent,
        "commission_source": "current Storm protocol fee snapshot",
        "spread_percent": config.spread_percent,
        "spread_source": "current Storm VPI spread snapshot",
        "slippage_percent": config.slippage_percent,
        "slippage_status": "BASELINE_ZERO_NOT_CALIBRATED_USE_PHASE_48_8_STRESS",
        "funding_rate_percent_per_day": config.funding_rate_percent_per_day,
        "funding_status": (
            "BASELINE_ZERO_NO_HISTORICAL_FUNDING_BACKFILL_USE_PHASE_48_8_STRESS"
        ),
        "market_impact_status": "NOT_BASELINE_ENGINE_INPUT_USE_PHASE_48_8_STRESS",
    }
    return config, evidence


def _validate_diagnostics(
    diagnostics: dict[str, Any],
    result: BacktestResult,
) -> None:
    if diagnostics["legacy_rejected_signals_equivalent"] != result.rejected_signals:
        raise RuntimeError(
            "signal attrition diagnostics diverged from legacy rejected_signals"
        )
    if diagnostics["trades_opened"] != len(result.trades):
        raise RuntimeError("signal attrition diagnostics diverged from trade count")
    if diagnostics["ready_for_risk_review"] != (
        diagnostics["entry_attempts"] + diagnostics["pending_signal_at_end"]
    ):
        raise RuntimeError("signal attrition diagnostics ready/entry accounting mismatch")


def run_locked_historical_baseline(
    dataset_dir: str | Path,
    *,
    evaluation_start: datetime,
    cost_service: StormCostService | None = None,
    code_revision: str = "UNKNOWN",
) -> dict[str, object]:
    """Run a research-only baseline from a sealed dataset with explicit warm-up."""

    bundle = load_locked_dataset(dataset_dir)
    symbol = bundle.manifest.get("symbol")
    dataset_fingerprint = bundle.manifest.get("dataset_bundle_fingerprint")
    manifest_fingerprint = bundle.manifest.get("manifest_fingerprint")
    dataset_code_revision = bundle.manifest.get("code_revision", "UNKNOWN")
    if not isinstance(symbol, str):
        raise ValueError("locked dataset symbol missing")
    if not isinstance(dataset_fingerprint, str):
        raise ValueError("locked dataset bundle fingerprint missing")
    if not isinstance(manifest_fingerprint, str):
        raise ValueError("locked dataset manifest fingerprint missing")
    if not isinstance(dataset_code_revision, str):
        raise ValueError("locked dataset code revision invalid")
    if evaluation_start.tzinfo is None:
        raise ValueError("evaluation_start must be timezone-aware")

    evaluation_start_utc = evaluation_start.astimezone(timezone.utc)
    dataset_start = _manifest_timestamp(
        bundle.manifest.get("requested_start"), "requested_start"
    )
    dataset_end = _manifest_timestamp(
        bundle.manifest.get("requested_end"), "requested_end"
    )
    if not dataset_start < evaluation_start_utc < dataset_end:
        raise ValueError(
            "evaluation_start must be strictly inside the locked dataset interval"
        )

    daily = bundle.candles_by_timeframe.get("1d")
    if daily is None:
        raise ValueError("locked dataset missing 1d candles")
    warmup_daily_candles = sum(
        1
        for candle in daily
        if candle.timestamp + timedelta(days=1) <= evaluation_start_utc
    )
    if warmup_daily_candles < _REQUIRED_DAILY_WARMUP:
        raise ValueError(
            "locked dataset has insufficient completed daily warm-up candles: "
            f"{warmup_daily_candles} < {_REQUIRED_DAILY_WARMUP}"
        )

    storm_costs = cost_service or StormCostService()
    config, cost_evidence = _cost_config(storm_costs, symbol)
    diagnostics = SignalAttritionDiagnostics()
    result = BacktestEngine(config).run(
        symbol,
        bundle.candles_by_timeframe,
        evaluation_start=evaluation_start_utc,
        diagnostic_observer=diagnostics.record,
    )
    diagnostic_payload = diagnostics.to_payload()
    _validate_diagnostics(diagnostic_payload, result)
    result_payload = _result_payload(result)
    strategy_payload = asdict(DEFAULT_RULES)
    config_payload = asdict(config)

    report: dict[str, object] = {
        "run_type": "LOCKED_HISTORICAL_BASELINE",
        "mode": "RESEARCH_PAPER_ONLY",
        "symbol": symbol,
        "dataset_provider": bundle.manifest.get("provider"),
        "dataset_version": bundle.manifest.get("dataset_version"),
        "dataset_requested_start": dataset_start,
        "dataset_requested_end": dataset_end,
        "evaluation_start": evaluation_start_utc,
        "evaluation_end": dataset_end,
        "warmup_required_daily_candles": _REQUIRED_DAILY_WARMUP,
        "warmup_completed_daily_candles": warmup_daily_candles,
        "dataset_bundle_fingerprint": dataset_fingerprint,
        "dataset_manifest_fingerprint": manifest_fingerprint,
        "dataset_source_shards_fingerprint": bundle.manifest.get(
            "source_shards_fingerprint"
        ),
        "dataset_code_revision": dataset_code_revision,
        "backtest_code_revision": code_revision,
        "strategy_rules": strategy_payload,
        "strategy_fingerprint": _fingerprint(strategy_payload),
        "backtest_config": config_payload,
        "config_fingerprint": _fingerprint(config_payload),
        "cost_evidence": cost_evidence,
        "signal_attrition": diagnostic_payload,
        "result": result_payload,
        "limitations": (
            "Gate.io candles are research OHLCV evidence; Storm is the execution venue.",
            "Pre-evaluation candles are warm-up only and are excluded from measured strategy decisions, rejections and entries.",
            "Signal attrition is observational evidence from the unchanged baseline execution path; it does not alter strategy thresholds or risk rules.",
            "This baseline uses current Storm protocol fee and VPI spread, not historical fee/spread series.",
            "Historical funding, calibrated slippage and market impact are not claimed by this baseline; Phase 48.8 stress qualification remains mandatory.",
            "A successful baseline run is not a live-trading authorization or a guarantee of future profitability.",
        ),
    }
    report["evidence_fingerprint"] = _fingerprint(report)
    return {str(key): _json_ready(value) for key, value in report.items()}
