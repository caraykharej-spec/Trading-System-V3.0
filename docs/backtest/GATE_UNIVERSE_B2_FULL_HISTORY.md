# Gate.io Universe Full-History Research Store — Backblaze B2

Status: **RESEARCH / PAPER ONLY**

## Objective

Maintain a durable, resumable and auditable historical OHLC research store for every current project-universe route that is available on Gate.io and for which Gate exposes a verified public range API.

The pipeline is intentionally separate from runtime state and execution. It does not authorize live trading, alter risk limits or change Storm's role as the reference-universe and reference-price authority.

## Universe authority

The discovery job builds the Gate-backed research universe from three sources:

1. the live Storm reference universe (`StormReferenceUniverseProvider`), which remains authoritative for current dynamic membership;
2. `config/universe.json`, retained as the static compatibility floor;
3. `config/market_data/source_registry.json`, which contains qualified explicit Gate spot, Gate futures and Gate TradFi routes, including price multipliers such as `1000PEPE -> PEPE_USDT * 1000` and `TON -> GRAM_USDT`.

For assets without an explicit Gate spot route, discovery chooses a tradable Gate spot market with quote priority `USDT`, then `USDC`, then `USD`.

Every discovered route is recorded independently. A canonical project symbol can therefore have more than one Gate research route when the source registry explicitly qualifies multiple Gate market types.

## Historical source policy

### Gate spot

Source: Gate public Spot v4 candlesticks.

- no API credential is required;
- the collector uses `from` / `to` time bounds;
- each request remains within Gate's 1,000-candle bound;
- collection is partitioned by calendar month and internally paginated;
- the canonical source grain is `15m`.

### Gate USDT perpetual futures

Source: Gate public Futures v4 candlesticks.

- no API credential is required;
- the collector uses `from` / `to` time bounds;
- each request remains within Gate's 2,000-candle bound;
- collection is partitioned by calendar month and internally paginated;
- the canonical source grain is `15m`.

### Gate TradFi

Gate TradFi routes are still discovered and represented in the transfer manifest, but the current verified project provider exposes only a bounded latest-window kline call. The historical sync therefore fails closed for those routes with:

`BLOCKED_FULL_HISTORY_UNAVAILABLE`

No bounded latest window is mislabeled as complete history. This limitation must be removed only after a historical `from/to` or equivalent archive contract has been verified and implemented.

## Timeframes

The project research timeframes are:

- `15m`
- `1h`
- `4h`
- `1d`

Only `15m` is fetched from Gate for this data-lake pipeline. Higher timeframes are deterministically derived from complete, contiguous 15-minute child bars. An incomplete parent interval is dropped rather than synthesized.

This reduces provider calls and makes multi-timeframe data internally consistent.

## Default historical interval

The workflow defaults to:

- start: `2013-01-01T00:00:00Z`
- end: start of the current UTC day, exclusive

The deliberately early default allows each Gate market to return all history it actually retains. Months with no returned candles are not fabricated.

Manual workflow dispatch can override both bounds.

## Storage format

Monthly partitions are stored as Parquet with ZSTD compression.

Logical columns:

- `canonical_symbol`
- `provider`
- `provider_symbol`
- `timeframe`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `price_multiplier`
- `source_timeframe`

OHLCV decimal values are serialized losslessly as decimal strings in the Parquet table so that ingestion does not introduce binary floating-point drift.

## Object layout

Completed calendar months:

```text
bronze/gate-history/v1/
  provider=<gateio|gateio_futures>/
    canonical=<canonical-symbol-slug>/
      market=<gate-market-slug>/
        timeframe=<15m|1h|4h|1d>/
          year=YYYY/
            month=MM/
              part-000.parquet
```

A partial current month is immutable by date rather than overwriting a completed partition:

```text
.../year=YYYY/month=MM/snapshot=YYYY-MM-DD/part-000.parquet
```

Per-route manifests:

```text
manifests/gate-history/v1/routes/
  provider=<provider>/
    canonical=<canonical-symbol-slug>/
      market=<gate-market-slug>/
        manifest.json
```

Per-run consolidated transfer evidence:

```text
manifests/gate-history/v1/runs/<github-run-id>.json
```

## Integrity and provenance

Each newly uploaded partition records:

- object key;
- SHA-256 of the local Parquet bytes;
- route identity;
- canonical symbol;
- provider symbol;
- price multiplier;
- timeframe;
- row count;
- first/last timestamp;
- run generation timestamp.

Existing completed monthly objects are reused unless the workflow is manually dispatched with `force=true`.

The collector never fills a missing candle synthetically. Missing 15-minute points are counted and recorded. For a market's first or last calendar month, the count can include time before listing or after delisting; therefore it is evidence of absent timestamps, not by itself proof of a provider outage.

## Workflow

Workflow file:

`.github/workflows/gate-universe-full-history-to-b2.yml`

Stages:

1. **Discover** — resolve current project universe and Gate routes.
2. **Sync** — fan out one matrix job per Gate route; fetch, normalize, resample, compress and upload.
3. **Summarize** — collect every route manifest, build run-level evidence and upload the consolidated manifest to B2.

The matrix fails independently per route (`fail-fast: false`) so one market cannot prevent evidence from being produced for other markets.

## Backblaze credentials

The workflow reuses the repository's established private B2 S3-compatible configuration:

- `B2_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_S3_ENDPOINT`
- `B2_BUCKET_NAME`

Credentials are read only from GitHub Actions secrets and are never written to artifacts or manifests.

## Completion semantics

Supported spot/futures route status:

- `COMPLETE` — historical data was returned with no missing 15-minute timestamps inside fetched months;
- `COMPLETE_WITH_RECORDED_GAPS` — data was transferred but absent 15-minute timestamps were observed and recorded;
- `NO_HISTORY_RETURNED` — Gate returned no data for the requested interval; run-level qualification fails.

TradFi route status:

- `BLOCKED_FULL_HISTORY_UNAVAILABLE` — current verified Gate/project interface cannot prove complete history; the run records the route but transfers no misleading partial dataset.

The consolidated workflow fails if a supported route is missing its summary or reports no historical data. A documented TradFi limitation is not silently converted into success for that route.

## Backtest consumption rule

Backtests must consume immutable completed-month objects and a specific run/route manifest. A current-month snapshot is research-freshness data and must not replace a previously locked OOS dataset without creating a new dataset identity/fingerprint.

Before any Phase 48 qualification run, the consumer must verify the manifest identity, partition list and content integrity and then lock the selected date range. Existing dataset versioning, OOS locking, reproducibility and B2 source-snapshot controls remain authoritative for qualification evidence.

## Operational commands

Discover the current Gate-backed project universe without B2 credentials:

```bash
python scripts/backtest/sync_gate_universe_history_to_b2.py \
  --discover-only \
  --output artifacts/gate-history-discovery.json
```

Sync one verified route when B2 environment variables are present:

```bash
python scripts/backtest/sync_gate_universe_history_to_b2.py \
  --canonical BTC/USDT \
  --base-asset BTC \
  --asset-class crypto \
  --provider gateio \
  --provider-symbol BTC_USDT \
  --start 2013-01-01T00:00:00Z \
  --end 2026-09-14T00:00:00Z
```

Normal production use is the GitHub Actions workflow rather than a laptop process.
