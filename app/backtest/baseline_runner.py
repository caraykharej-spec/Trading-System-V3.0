from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, BacktestResult
from app.data.market_data import Candle, MarketDataRequest
from app.data.providers.base import MarketDataProvider
from app.data.providers.gateio import GateIOProvider
from app.data.versioned_dataset import DatasetProvenance, build_versioned_dataset
from app.storm_costs import StormCostService
from app.strategy.rules import DEFAULT_RULES

_REQUIRED_TIMEFRAMES = ("15m", "1h", "4h", "1d")
_TIMEFRAME_MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}


@dataclass(frozen=True)
class BaselineRunPolicy:
    candle_limit: int = 1000
    dataset_version: str = "1.0.0"
    minimum_candles_per_timeframe: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.candle_limit <= 1000:
            raise ValueError("candle_limit must be in [1, 1000]")
        if self.minimum_candles_per_timeframe < 2:
            raise ValueError("minimum_candles_per_timeframe must be at least 2")
        if self.minimum_candles_per_timeframe > self.candle_limit:
            raise ValueError("minimum_candles_per_timeframe cannot exceed candle_limit")


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
    encoded = json.dumps(
        _json_ready(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _drop_incomplete(
    candles: list[Candle], timeframe: str, observed_at: datetime
) -> list[Candle]:
    duration = timedelta(minutes=_TIMEFRAME_MINUTES[timeframe])
    return [
        candle
        for candle in candles
        if candle.timestamp + duration <= observed_at
    ]


def _cost_config(service: StormCostService, symbol: str) -> tuple[BacktestConfig, dict[str, object]]:
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
        "funding_status": "BASELINE_ZERO_NO_HISTORICAL_FUNDING_BACKFILL_USE_PHASE_48_8_STRESS",
        "market_impact_status": "NOT_BASELINE_ENGINE_INPUT_USE_PHASE_48_8_STRESS",
    }
    return config, evidence


def _result_payload(result: BacktestResult) -> dict[str, object]:
    trades = []
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


def run_live_baseline(
    *,
    symbol: str = "BTC/USDT",
    policy: BaselineRunPolicy | None = None,
    candle_provider: MarketDataProvider | None = None,
    cost_service: StormCostService | None = None,
    observed_at: datetime | None = None,
    code_revision: str = "UNKNOWN",
) -> dict[str, object]:
    """Run a research-only baseline using real public OHLCV and current Storm costs.

    The run intentionally does not claim historical funding/slippage/market-impact truth.
    Those dimensions remain explicit Phase 48.8 stress inputs until historical evidence exists.
    """

    applied = policy or BaselineRunPolicy()
    provider = candle_provider or GateIOProvider()
    storm_costs = cost_service or StormCostService()
    retrieved_at = observed_at or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    retrieved_at = retrieved_at.astimezone(timezone.utc)

    candles_by_timeframe: dict[str, list[Candle]] = {}
    manifests: dict[str, dict[str, object]] = {}
    for timeframe in _REQUIRED_TIMEFRAMES:
        request = MarketDataRequest(
            symbol=symbol,
            timeframe=timeframe,
            limit=applied.candle_limit,
        )
        candles = provider.get_candles(request)
        completed = _drop_incomplete(candles, timeframe, retrieved_at)
        if len(completed) < applied.minimum_candles_per_timeframe:
            raise ValueError(
                f"insufficient completed {timeframe} candles: "
                f"{len(completed)} < {applied.minimum_candles_per_timeframe}"
            )
        candles_by_timeframe[timeframe] = completed
        pair = symbol.replace("/", "_").upper()
        source_uri = (
            "https://api.gateio.ws/api/v4/spot/candlesticks"
            f"?currency_pair={pair}&interval={timeframe}&limit={applied.candle_limit}"
        )
        dataset = build_versioned_dataset(
            dataset_id=f"{symbol.replace('/', '-').lower()}-{timeframe}-gateio-baseline",
            version=applied.dataset_version,
            symbol=symbol,
            timeframe=timeframe,
            candles=completed,
            provenance=DatasetProvenance(
                provider=getattr(provider, "name", provider.__class__.__name__),
                provider_symbol=pair,
                retrieved_at=retrieved_at,
                source_uri=source_uri,
                license_id="gateio-public-api-v4",
            ),
            split_adjusted=False,
            created_at=retrieved_at,
        )
        manifests[timeframe] = dataset.to_manifest()

    config, cost_evidence = _cost_config(storm_costs, symbol)
    result = BacktestEngine(config).run(symbol, candles_by_timeframe)
    result_payload = _result_payload(result)
    strategy_payload = asdict(DEFAULT_RULES)
    config_payload = asdict(config)

    identity_payload = {
        "symbol": symbol,
        "dataset_content_sha256": {
            timeframe: manifest["content_sha256"]
            for timeframe, manifest in sorted(manifests.items())
        },
        "strategy": strategy_payload,
        "config": config_payload,
        "cost_evidence": cost_evidence,
        "result": result_payload,
    }
    report: dict[str, object] = {
        "run_type": "LIVE_PUBLIC_DATA_BASELINE",
        "mode": "RESEARCH_PAPER_ONLY",
        "symbol": symbol,
        "retrieved_at": retrieved_at,
        "code_revision": code_revision,
        "data_provider": getattr(provider, "name", provider.__class__.__name__),
        "dataset_manifests": manifests,
        "dataset_bundle_fingerprint": _fingerprint(
            identity_payload["dataset_content_sha256"]
        ),
        "strategy_rules": strategy_payload,
        "strategy_fingerprint": _fingerprint(strategy_payload),
        "backtest_config": config_payload,
        "config_fingerprint": _fingerprint(config_payload),
        "cost_evidence": cost_evidence,
        "result": result_payload,
        "limitations": (
            "Gate.io candles are a public OHLCV proxy selected for research; Storm is the execution venue.",
            "This baseline uses current Storm protocol fee and VPI spread, not historical fee/spread series.",
            "Historical funding, calibrated slippage and market impact are not claimed by this baseline; Phase 48.8 stress qualification remains mandatory.",
            "A successful baseline run is not a live-trading authorization or a guarantee of future profitability.",
        ),
    }
    report["evidence_fingerprint"] = _fingerprint(identity_payload)
    return _json_ready(report)
