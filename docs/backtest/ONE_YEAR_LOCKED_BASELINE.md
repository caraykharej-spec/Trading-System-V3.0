# One-Year Locked Baseline

Status: CHECKPOINT 4 IMPLEMENTATION

This checkpoint extends the short live-data smoke baseline into a reproducible one-year BTC/USDT research baseline without coupling historical collection to backtest execution.

## Fixed evidence interval

- Symbol: `BTC/USDT`
- Provider: Gate.io public OHLCV
- Start: `2025-09-13T00:00:00Z`
- End: `2026-09-13T00:00:00Z`
- Duration: 365 complete UTC days
- Required timeframes: `15m`, `1h`, `4h`, `1d`
- Expected complete candles after successful gap-free assembly:
  - `15m`: 35,040
  - `1h`: 8,760
  - `4h`: 2,190
  - `1d`: 365

The end boundary is exclusive. Every accepted candle is therefore complete before `2026-09-13T00:00:00Z`.

## Reliability model

The year is not downloaded as one monolithic task. It is split into four independent contiguous shards:

1. `2025-09-13` → `2025-12-13`
2. `2025-12-13` → `2026-03-13`
3. `2026-03-13` → `2026-06-13`
4. `2026-06-13` → `2026-09-13`

Only two shard jobs run concurrently to reduce provider pressure. Each shard retains the existing bounded Gate.io request windows, checkpoint files, checksum validation, retries, exponential backoff, complete-range validation and locked manifest sealing.

Each successful shard is uploaded as an independent GitHub Actions artifact. A later assembly job downloads only successful locked artifacts and calls `load_locked_dataset()` on every shard before accepting any candle.

## Annual lock assembly

`merge_locked_dataset_shards()` fails closed unless:

- every shard passes its own manifest, file checksum, canonical content hash and range validation;
- all shards use the same provider and symbol;
- shard ranges are exactly contiguous, with neither overlap nor gap;
- merged timestamps contain no duplicates;
- every merged timeframe passes the normal data-quality cadence rules;
- the merged first and final candle exactly match the requested annual boundaries.

The annual dataset is then re-versioned, written to new locked JSONL files, assigned a new content fingerprint, linked to all source shard fingerprints, and finally passed through `load_locked_dataset()` again before being released to the backtest job.

The baseline job never refetches OHLCV from the network.

## Controlled baseline costs

The annual baseline uses the existing Strategy Engine and Backtest Engine. Current Storm protocol fee and VPI spread are captured at execution time and sealed into the report.

Historical funding, calibrated slippage and market impact are not fabricated. Their baseline values remain zero and are explicitly marked as requiring the existing Phase 48.8 stress qualification.

## Qualification boundary

This checkpoint answers only:

> What does the current strategy do on one verified, gap-free, one-year BTC/USDT research dataset under the documented baseline cost assumptions?

It does **not** make the strategy statistically qualified, authorize LIVE trading, or replace locked OOS, walk-forward, regime, parameter, Monte Carlo or cost-robustness evidence.

No strategy score, confidence, risk-reward or risk thresholds are relaxed to manufacture trades.
