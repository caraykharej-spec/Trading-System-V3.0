# Historical 15m Repair

## Purpose

Replace the source-limited Yahoo 15-minute research history for the 26
non-crypto Storm assets without changing live route priority or Storm price
authority.

The reviewed source split is:

- 16 US equities: Alpaca historical SIP, `adjustment=all`, regular session only;
- 6 FX pairs, XAU, XAG, Brent and SPX: HistData Generic ASCII BID M1 archives;
- 15m is provider-backed; 1h, 4h and 1d are deterministically derived;
- missing sessions are preserved and never forward-filled;
- `SPXUSD` is recorded as a provider proxy for SPX, not an exchange cash-index
  print.

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
2. Targeted HistData smoke: set `base_asset=EUR`, `start=2024-11-01T00:00:00Z`
   and `end=2024-12-01T00:00:00Z`; confirm `PASS_TARGETED_15M_REPAIR` and inspect
   the month-level timing evidence.
3. Targeted full-range HistData validation: set `base_asset=EUR`, restore the
   default start and leave end empty. Confirm `PASS_TARGETED_15M_REPAIR`.
4. Full transfer: leave `base_asset` empty. Keep `force=false`. The full run is
   valid only when all 26 routes finish and the run manifest reports
   `PASS_COMPLETE_15M_REPAIR`.
5. Record the full workflow run ID. Targeted run IDs are intentionally stored
   separately and cannot satisfy global qualification.
6. Run **Global Historical Data Qualification** with the existing Gate and
   Yahoo IDs plus `extended_15m_run_id=<full repair workflow run ID>`.
7. Inspect the qualification artifact. The 26 repaired assets must select
   either `alpaca_sip` or `histdata` with identity policy
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
- Monthly Parquet objects are SHA-256 verified and safely reused on rerun.
- A targeted run is diagnostic evidence only, never a complete global source
  manifest.

## HistData acquisition policy

HistData replaces Dukascopy as the reviewed acquisition provider for the ten
non-equity routes. Historical years are fetched as one annual ZIP archive;
the active year is fetched as monthly ZIP archives. Each archive contains
Generic ASCII BID M1 candles which are parsed locally and aggregated to 15m.
This removes the latency-heavy one-request-per-calendar-day design.

HistData timestamps are fixed EST without daylight-saving adjustment. They are
converted to timezone-aware UTC before filtering or aggregation. UTC month
boundaries may require the preceding source month/year archive; the downloader
loads both scopes and de-duplicates timestamps fail-closed. HTTP and transport
failures use five bounded attempts with 2-to-30-second exponential delays.
HTML/error responses are rejected because the payload must be a valid ZIP.

## HistData checkpoint, provenance and progress policy

HistData acquisition is committed one UTC calendar month at a time. A monthly
checkpoint is written only after all four derived partitions (`15m`, `1h`,
`4h`, and `1d`) have been uploaded and SHA-256 verified. On a later
`force=false` run, each checkpoint's route, exact requested month range, four
partition records, and remote object hashes are verified before that month is
skipped. An invalid or stale checkpoint is ignored and the month is rebuilt.

Existing Dukascopy objects and checkpoints are not deleted, but they are not
reused as HistData evidence. Provider-specific object namespaces prevent a
mixed-provider route from being presented as a clean HistData dataset. The
manifest records `clean_histdata_namespace_no_cross_provider_reuse` as the
migration policy.

This makes a mid-month provider failure resumable without accepting a partial
route as complete. The final route manifest remains fail-closed and is written
only after every requested month is complete. `force=true` deliberately
bypasses checkpoint reuse. A partial current month is reusable only when its
requested end timestamp exactly matches, preventing a stale checkpoint from
hiding newly available data. Structured log events record month start, reuse or
completion, elapsed seconds, archive scopes and produced rows. Error summaries
record the failed month, completed/reused months and failed archive scope.

## Validation scopes

The workflow passes an explicit validation scope to every route job. A
`targeted` run validates non-empty data, OHLC/duplicate/SHA policies and both
edges of the requested interval, allowing normal market-closure gaps of up to
14 days. It does not enforce the route's 1,095-day qualification minimum and
can produce only `PASS_TARGETED_15M_REPAIR`.

A `full` run applies the same requested-range checks and additionally enforces
the minimum history span for every non-listing-limited route. Only a successful
26-route full run can produce `PASS_COMPLETE_15M_REPAIR` and be supplied to
global qualification. The command-line default remains `full` so a missing
scope cannot accidentally weaken qualification.
