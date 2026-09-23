# Historical 15m Repair

## Purpose

Replace the source-limited Yahoo 15-minute research history for the 26
non-crypto Storm assets without changing live route priority or Storm price
authority.

The reviewed source split is:

- 16 US equities: Alpaca historical SIP, `adjustment=all`, regular session only;
- 6 FX pairs, XAU, XAG, Brent and USA500: Dukascopy BID minute candles;
- 15m is provider-backed; 1h, 4h and 1d are deterministically derived;
- missing sessions are preserved and never forward-filled;
- `USA500IDXUSD` is recorded as a CFD proxy for SPX, not the cash index.

The locked source registry is
`config/market_data/historical_15m_repair_sources.json`. Its default lower
bound is `2022-01-01T00:00:00Z`, which is more than the three-year minimum at
the time this policy was introduced. CRCL is explicitly listing-limited; no
pre-listing candles may be synthesized.

## Required secrets

Existing HF S3 secrets remain unchanged. Add these two repository secrets for
the free Alpaca Basic account:

- `ALPACA_API_KEY_ID`
- `ALPACA_API_SECRET_KEY`

The equity route is fail-closed to `feed=sip`. It does not silently downgrade
to IEX because IEX volume is not representative of the full US market.

## Operator run order

Use **Actions → Historical 15m Repair to HF → Run workflow**.

1. Targeted equity validation: set `base_asset=AAPL`; leave start/end at their
   defaults. Confirm `PASS_TARGETED_15M_REPAIR`.
2. Targeted Dukascopy validation: set `base_asset=EUR`; confirm
   `PASS_TARGETED_15M_REPAIR`.
3. Full transfer: leave `base_asset` empty. Keep `force=false`. The full run is
   valid only when all 26 routes finish and the run manifest reports
   `PASS_COMPLETE_15M_REPAIR`.
4. Record the full workflow run ID. Targeted run IDs are intentionally stored
   separately and cannot satisfy global qualification.
5. Run **Global Historical Data Qualification** with the existing Gate and
   Yahoo IDs plus `extended_15m_run_id=<full repair workflow run ID>`.
6. Inspect the qualification artifact. The 26 repaired assets must select
   either `alpaca_sip` or `dukascopy` with identity policy
   `historical_15m_repair_backtest_ready`.

Do not start Phase 48.8 from old evidence. A changed historical source changes
the locked dataset and invalidates prior Phase 48.2–48.7 statistical evidence.
After qualification passes, rebuild the locked OOS evidence first; run the
large matrix and robustness workflows only after reviewing that smaller result.

## Failure boundaries

- Missing Alpaca secrets stop equities before any fallback is attempted.
- A route with less than 1,095 days of observed history fails, except an
  explicitly listing-limited route.
- OHLC invariant violations are dropped and counted; values are never clamped.
- Conflicting duplicate timestamps fail the route.
- Yearly Parquet objects are SHA-256 verified and safely reused on rerun.
- A targeted run is diagnostic evidence only, never a complete global source
  manifest.

## Dukascopy transient-failure policy

Daily Dukascopy requests are paced at 0.2 seconds. HTTP `408`, `429`, `500`,
`502`, `503` and `504` are retried up to seven total attempts. Transport errors
such as connection resets and timeouts use a separate ten-attempt budget. Both
use exponential delays of 2, 4, 8, 16, 32 and 60 seconds plus bounded jitter. A
valid `Retry-After` header is honored when it requests a longer wait. HTTP `404`
remains an expected empty source day; other 4xx responses fail immediately.
Errors identify the exact failed source date.

An exhausted daily request is deferred instead of immediately aborting its
month. The downloader finishes the other days and makes three total sweeps of
the unresolved dates, with a 60-second cooldown between sweeps. A day that is
still unresolved remains a hard failure; an HTTP/provider error is never
silently treated as a market holiday.

## Dukascopy checkpoint and resume policy

Dukascopy acquisition is committed one calendar month at a time. A monthly
checkpoint is written only after all four derived partitions (`15m`, `1h`,
`4h`, and `1d`) have been uploaded and SHA-256 verified. On a later
`force=false` run, each checkpoint's route, exact requested month range, four
partition records, and remote object hashes are verified before that month is
skipped. An invalid or stale checkpoint is ignored and the month is rebuilt.

Backward compatibility is deliberate: the downloader first checks the yearly
checkpoints created by the previous implementation. A valid legacy year is
reused as a whole; monthly checkpoints are considered only when no valid yearly
checkpoint covers that range. Existing completed work is therefore not lost
during migration.

This makes a mid-month provider failure resumable without accepting a partial
route as complete. The final route manifest remains fail-closed and is written
only after every requested month is complete. `force=true` deliberately
bypasses checkpoint reuse. A partial current month is reusable only when its
requested end timestamp exactly matches, preventing a stale checkpoint from
hiding newly available data. Error summaries include reused legacy years,
reused/written months, the failed month, and unresolved source dates.
