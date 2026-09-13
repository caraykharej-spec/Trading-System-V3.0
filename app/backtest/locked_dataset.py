from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.data.historical_backfill import load_locked_dataset
from app.strategy.rules import DEFAULT_RULES, StrategyRules

from .engine import BacktestEngine
from .models import BacktestConfig, BacktestResult


@dataclass(frozen=True)
class LockedBacktestEvidence:
    symbol: str
    dataset_bundle_fingerprint: str
    manifest_fingerprint: str
    code_revision: str
    result: BacktestResult


def run_locked_dataset_backtest(
    dataset_dir: str | Path,
    *,
    config: BacktestConfig | None = None,
    rules: StrategyRules = DEFAULT_RULES,
    evaluation_start: datetime | None = None,
) -> LockedBacktestEvidence:
    """Run the backtest only after the locked dataset passes integrity verification."""

    bundle = load_locked_dataset(dataset_dir)
    symbol = bundle.manifest.get("symbol")
    dataset_fingerprint = bundle.manifest.get("dataset_bundle_fingerprint")
    manifest_fingerprint = bundle.manifest.get("manifest_fingerprint")
    code_revision = bundle.manifest.get("code_revision", "UNKNOWN")
    if not isinstance(symbol, str):
        raise ValueError("locked dataset symbol missing")
    if not isinstance(dataset_fingerprint, str):
        raise ValueError("locked dataset bundle fingerprint missing")
    if not isinstance(manifest_fingerprint, str):
        raise ValueError("locked dataset manifest fingerprint missing")
    if not isinstance(code_revision, str):
        raise ValueError("locked dataset code revision invalid")

    result = BacktestEngine(config, rules=rules).run(
        symbol,
        bundle.candles_by_timeframe,
        evaluation_start=evaluation_start,
    )
    return LockedBacktestEvidence(
        symbol=symbol,
        dataset_bundle_fingerprint=dataset_fingerprint,
        manifest_fingerprint=manifest_fingerprint,
        code_revision=code_revision,
        result=result,
    )
