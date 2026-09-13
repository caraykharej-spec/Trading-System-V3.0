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
- At least 200 completed candles per timeframe are required because strategy trend analysis depends on EMA200. The requested provider limit must be greater than the completed-candle minimum so an open candle can be removed without silently making strategy evaluation impossible.
- Every timeframe is passed through `build_versioned_dataset`, which rejects duplicates, OHLC integrity failures and unexpected gaps and produces a content SHA-256.
- Gate.io provenance is derived from the actual Gate.io provider instance. Any injected non-Gate provider must supply an explicit provenance builder; contradictory or assumed provenance is rejected.

The initial 1,000-candle run is a baseline/smoke historical run, not the final long-horizon qualification dataset. A deeper historical collector must paginate/backfill and lock a longer dataset before OOS, walk-forward and final high-run-count qualification are claimed.

## Cost contract

The baseline reads the current Storm market cost snapshot and maps the protocol fee and VPI spread into `BacktestConfig`. Missing required fee/spread evidence fails closed.

Historical funding, calibrated slippage and market impact are deliberately not invented. They remain explicit zero/unmodeled baseline dimensions and must be exercised through the Phase 48.8 cost-stress qualification until time-series historical evidence is available.

## Evidence

The JSON artifact records:

- complete dataset manifests and content fingerprints for all four timeframes;
- strategy-rule fingerprint;
- backtest configuration fingerprint;
- current Storm cost evidence and modeling limitations;
- aggregate metrics and trade-level economic records without random position IDs;
- the exact code revision;
- one canonical evidence fingerprint that seals the complete audit-relevant report, including code revision and dataset provenance.

## Reliability execution model

Backtest work is intentionally checkpointed rather than executed as one long monolithic job:

1. establish and merge the baseline runner;
2. collect historical data in bounded, retryable backfill chunks and persist a locked dataset artifact;
3. validate and fingerprint the locked dataset before running research batches;
4. run development robustness in small independent batches (normally tens of runs, not 1,000 at once);
5. persist one evidence artifact per batch so a failed or interrupted batch can be repeated without rerunning completed work;
6. reserve larger 500–1,000-run matrices for final qualification only, sharded into bounded jobs.

The baseline GitHub Actions job has an explicit 15-minute timeout. Future backfill and robustness workflows must use bounded job timeouts, deterministic batch IDs, fail-closed validation and artifact checkpoints. This keeps failures local, makes retries reproducible and avoids coupling the entire qualification process to one long-running execution.

## Execution

```bash
python scripts/backtest/run_live_baseline.py \
  --symbol BTC/USDT \
  --limit 1000 \
  --dataset-version 1.0.0 \
  --output artifacts/backtest/btc-usdt-baseline.json
```

The `Baseline Historical Backtest` GitHub Actions workflow executes the same command against live public data and uploads the JSON evidence artifact.
