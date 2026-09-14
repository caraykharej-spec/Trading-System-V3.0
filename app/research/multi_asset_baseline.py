from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

_REQUIRED_WARMUP_DAILY_CANDLES = 200
_REQUIRED_RUN_TYPE = "LOCKED_HISTORICAL_BASELINE"
_REQUIRED_MODE = "RESEARCH_PAPER_ONLY"


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _require_string(report: Mapping[str, Any], key: str) -> str:
    value = report.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"baseline report {key} missing or invalid")
    return value


def _require_int(report: Mapping[str, Any], key: str) -> int:
    value = report.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"baseline report {key} missing or invalid")
    return value


def _result(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = report.get("result")
    if not isinstance(value, Mapping):
        raise ValueError("baseline report result missing or invalid")
    return value


def _decimal_or_none(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool):
        raise ValueError(f"baseline result {field} invalid")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"baseline result {field} invalid") from exc


def _canonical_asset(report: Mapping[str, Any]) -> dict[str, object]:
    if report.get("run_type") != _REQUIRED_RUN_TYPE:
        raise ValueError("unexpected baseline run_type")
    if report.get("mode") != _REQUIRED_MODE:
        raise ValueError("baseline must be RESEARCH_PAPER_ONLY")

    warmup = _require_int(report, "warmup_completed_daily_candles")
    if warmup < _REQUIRED_WARMUP_DAILY_CANDLES:
        raise ValueError(
            "baseline warm-up is insufficient: "
            f"{warmup} < {_REQUIRED_WARMUP_DAILY_CANDLES}"
        )

    result = _result(report)
    trade_count = result.get("trade_count")
    rejected_signals = result.get("rejected_signals")
    if isinstance(trade_count, bool) or not isinstance(trade_count, int) or trade_count < 0:
        raise ValueError("baseline result trade_count invalid")
    if (
        isinstance(rejected_signals, bool)
        or not isinstance(rejected_signals, int)
        or rejected_signals < 0
    ):
        raise ValueError("baseline result rejected_signals invalid")

    total_return = _decimal_or_none(result.get("total_return_percent"), "total_return_percent")
    max_drawdown = _decimal_or_none(
        result.get("max_drawdown_percent"), "max_drawdown_percent"
    )
    win_rate = _decimal_or_none(result.get("win_rate_percent"), "win_rate_percent")
    profit_factor = _decimal_or_none(result.get("profit_factor"), "profit_factor")

    return {
        "symbol": _require_string(report, "symbol"),
        "dataset_bundle_fingerprint": _require_string(
            report, "dataset_bundle_fingerprint"
        ),
        "dataset_manifest_fingerprint": _require_string(
            report, "dataset_manifest_fingerprint"
        ),
        "dataset_source_shards_fingerprint": report.get(
            "dataset_source_shards_fingerprint"
        ),
        "evidence_fingerprint": _require_string(report, "evidence_fingerprint"),
        "strategy_fingerprint": _require_string(report, "strategy_fingerprint"),
        "config_fingerprint": _require_string(report, "config_fingerprint"),
        "dataset_code_revision": _require_string(report, "dataset_code_revision"),
        "backtest_code_revision": _require_string(report, "backtest_code_revision"),
        "dataset_requested_start": _require_string(report, "dataset_requested_start"),
        "dataset_requested_end": _require_string(report, "dataset_requested_end"),
        "evaluation_start": _require_string(report, "evaluation_start"),
        "evaluation_end": _require_string(report, "evaluation_end"),
        "warmup_completed_daily_candles": warmup,
        "trade_count": trade_count,
        "rejected_signals": rejected_signals,
        "total_return_percent": None if total_return is None else str(total_return),
        "max_drawdown_percent": None if max_drawdown is None else str(max_drawdown),
        "win_rate_percent": None if win_rate is None else str(win_rate),
        "profit_factor": None if profit_factor is None else str(profit_factor),
        "profitable": bool(total_return is not None and total_return > 0),
    }


def aggregate_multi_asset_baselines(
    reports: Iterable[Mapping[str, Any]],
) -> dict[str, object]:
    """Validate and aggregate comparable locked baselines without pooling equity."""

    assets = [_canonical_asset(report) for report in reports]
    if len(assets) < 2:
        raise ValueError("multi-asset baseline requires at least two reports")
    assets.sort(key=lambda item: str(item["symbol"]))

    symbols = [str(item["symbol"]) for item in assets]
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate baseline symbol detected")

    comparable_fields = (
        "dataset_requested_start",
        "dataset_requested_end",
        "evaluation_start",
        "evaluation_end",
        "strategy_fingerprint",
        "dataset_code_revision",
        "backtest_code_revision",
    )
    for field in comparable_fields:
        values = {str(item[field]) for item in assets}
        if len(values) != 1:
            raise ValueError(f"baseline reports disagree on {field}")

    dataset_fingerprints = [str(item["dataset_bundle_fingerprint"]) for item in assets]
    evidence_fingerprints = [str(item["evidence_fingerprint"]) for item in assets]
    if len(set(dataset_fingerprints)) != len(dataset_fingerprints):
        raise ValueError("duplicate dataset fingerprint across different assets")
    if len(set(evidence_fingerprints)) != len(evidence_fingerprints):
        raise ValueError("duplicate evidence fingerprint across different assets")

    total_trade_count = sum(int(item["trade_count"]) for item in assets)
    total_rejected_signals = sum(int(item["rejected_signals"]) for item in assets)
    profitable_asset_count = sum(1 for item in assets if bool(item["profitable"]))

    aggregate: dict[str, object] = {
        "schema_version": "1.0",
        "run_type": "MULTI_ASSET_LOCKED_BASELINE_AGGREGATE",
        "mode": _REQUIRED_MODE,
        "asset_count": len(assets),
        "symbols": symbols,
        "dataset_requested_start": assets[0]["dataset_requested_start"],
        "dataset_requested_end": assets[0]["dataset_requested_end"],
        "evaluation_start": assets[0]["evaluation_start"],
        "evaluation_end": assets[0]["evaluation_end"],
        "strategy_fingerprint": assets[0]["strategy_fingerprint"],
        "dataset_code_revision": assets[0]["dataset_code_revision"],
        "backtest_code_revision": assets[0]["backtest_code_revision"],
        "total_trade_count": total_trade_count,
        "total_rejected_signals": total_rejected_signals,
        "profitable_asset_count": profitable_asset_count,
        "assets": assets,
        "interpretation_limits": (
            "Per-asset results are descriptive research evidence and are not pooled into a portfolio equity curve.",
            "Summed trade counts expand the observed sample but do not establish statistical independence or strategy qualification.",
            "Different config fingerprints are allowed because venue cost evidence can differ by asset.",
            "This aggregate does not authorize LIVE trading or imply future profitability.",
        ),
    }
    aggregate["aggregate_fingerprint"] = _fingerprint(aggregate)
    return aggregate
