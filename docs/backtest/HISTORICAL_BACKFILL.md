# Historical Backfill and Dataset Lock

## Purpose

Checkpoint 2 converts public Gate.io OHLCV into a resumable, validated, offline dataset for repeatable research and validation runs without re-querying the provider every time.

## Reliability model

The collector uses bounded time windows instead of one long request. Gate.io documents a maximum of 1,000 candlesticks per request and rejects `limit` when `from` or `to` is supplied. The default collector uses 900 theoretical points per window.

Each completed request is written atomically as a self-checking checkpoint. A rerun reuses valid checkpoint files and performs no network call for those windows. Corrupt or contradictory checkpoint metadata fails closed.

Adjacent windows overlap by one timestamp. Exact duplicate candles are deduplicated, while conflicting values for the same timestamp fail closed. This makes the collector insensitive to endpoint-inclusivity differences without silently accepting inconsistent data.

Transient provider errors are retried with deterministic exponential backoff. The complete timeframe is then checked for exact requested start/end coverage, strict chronology, missing intervals, OHLC integrity, and duplicate conflicts.

## Locked output

The output directory contains:

- `checkpoints/<symbol>/<timeframe>/...json`: resumable request checkpoints;
- `locked/<symbol>/<timeframe>.jsonl`: canonical offline candles;
- `manifest.json`: provenance, per-file SHA-256, dataset content hashes, checkpoint audit metadata, code revision and bundle fingerprints.

`dataset_bundle_fingerprint` is stable for the same symbol, requested range, version and candle content. `manifest_fingerprint` seals the full audit manifest, including code revision, policy and retrieval metadata.

`load_locked_dataset()` verifies the manifest fingerprint, bundle fingerprint, locked-file checksum, canonical candle content hash, full data-quality rules and exact range boundaries before returning any candles.

## Staged use

Use a short range in CI to prove pagination, resume and locking. Do not commit market data to Git. For a long research dataset, run the same collector locally or in a dedicated artifact job and retain the output directory as one immutable evidence bundle.

A one-year BTC/USDT collection is a suitable next data-engineering test after this checkpoint is merged. Long-horizon execution should be profiled separately because the current snapshot engine is not yet optimized for tens of thousands of 15-minute evaluations.

## Example

```bash
python scripts/backtest/backfill_historical_dataset.py \
  --symbol BTC/USDT \
  --start 2025-09-01T00:00:00Z \
  --end 2026-09-01T00:00:00Z \
  --dataset-version 1.0.0 \
  --output-dir artifacts/backfill/btc-usdt-1y
```

Re-running the same command resumes from the existing valid checkpoints.
