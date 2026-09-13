# Baseline Historical Backtest

## Purpose

This runner starts the real Phase 48 validation path with public historical OHLCV while preserving the production data and cost boundaries already implemented by the project.

The baseline is research/PAPER evidence only. It cannot authorize live execution.

## Data contract

- Canonical symbol for the first run: `BTC/USDT`.
- OHLCV source: public Gate.io Spot v4 candlesticks.
- Required timeframes: `15m`, `1h`, `4h`, `1d`.
- Maximum provider request: 1,000 candles per timeframe.
- The still-open candle is excluded before validation.
- Every timeframe is passed through `build_versioned_dataset`, which rejects duplicates, OHLC integrity failures and unexpected gaps and produces a content SHA-256.

The initial 1,000-candle run is a baseline/smoke historical run, not the final long-horizon qualification dataset. A deeper historical collector must paginate/backfill and lock a longer dataset before OOS, walk-forward and 1,000-run final qualification are claimed.

## Cost contract

The baseline reads the current Storm market cost snapshot and maps the protocol fee and VPI spread into `BacktestConfig`. Missing required fee/spread evidence fails closed.

Historical funding, calibrated slippage and market impact are deliberately not invented. They remain explicit zero/unmodeled baseline dimensions and must be exercised through the Phase 48.8 cost-stress qualification until time-series historical evidence is available.

## Evidence

The JSON artifact records:

- dataset manifests and content fingerprints for all four timeframes;
- strategy-rule fingerprint;
- backtest configuration fingerprint;
- current Storm cost evidence and modeling limitations;
- aggregate metrics and trade-level economic records without random position IDs;
- a canonical evidence fingerprint.

## Execution

```bash
python scripts/backtest/run_live_baseline.py \
  --symbol BTC/USDT \
  --limit 1000 \
  --dataset-version 1.0.0 \
  --output artifacts/backtest/btc-usdt-baseline.json
```

The `Baseline Historical Backtest` GitHub Actions workflow executes the same command against live public data and uploads the JSON evidence artifact.
