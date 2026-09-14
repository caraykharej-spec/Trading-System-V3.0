# Gate.io Universe Full-History Research Store — Backblaze B2

Status: **RESEARCH / PAPER ONLY**

## Objective

Maintain a durable, resumable and auditable OHLC research store in Backblaze B2 for every current project-universe route that is available on Gate.io and has a verified complete historical source.

The pipeline is isolated from execution. It does not authorize live trading, change risk limits, or change Storm's role as the reference-universe and reference-price authority.

## Universe authority

Discovery combines:

1. the live Storm reference universe (`StormReferenceUniverseProvider`);
2. `config/universe.json` as the static compatibility floor;
3. `config/market_data/source_registry.json` for explicitly qualified Gate spot, Gate futures and Gate TradFi routes, including price multipliers such as `1000PEPE -> PEPE_USDT * 1000` and mappings such as `TON -> GRAM_USDT`.

When no explicit Gate spot route exists, discovery selects a currently tradable Gate spot market using quote priority `USDT`, then `USDC`, then `USD`.

Every Gate route is represented independently, so one canonical project symbol can retain more than one qualified Gate market route.

## Historical source policy

### Gate Historical Quotation archive — authoritative backfill source

The backfill uses Gate's public Historical Quotation download service at `download.gatedata.org`.

Current Gate documentation states that downloadable K-line history is supported from **January 2023**. The pipeline therefore uses `2023-01-01T00:00:00Z` as the default and minimum authoritative archive start for v2.

For both Spot and USDT-M Futures, Gate publishes daily K-line files using the documented pattern:

```text
https://download.gatedata.org/<biz>/candlesticks_<interval>/YYYYMM/<market>-YYYYMMDD.csv.gz
```

where `biz` is:

- `spot` for Gate Spot;
- `futures_usdt` for USDT-M Futures.

The archive offers `1m`, `5m`, `1h`, `4h`, `1d` and `7d` K-line granularities. The project ingests **5m** as the canonical source grain and deterministically derives the project's required `15m`, `1h`, `4h` and `1d` bars.

### REST tail fallback

The Gate REST candlestick APIs are not used as the long-range archive source. They are used only as a bounded fallback for an archive day missing inside the most recent 30-day window. This covers publication lag without pretending REST is an unlimited historical store.

The fallback remains subject to Gate's public endpoint limits:

- Spot: maximum 1,000 candlesticks per request;
- Futures: maximum 2,000 candlesticks per request.

### Gate TradFi

Gate TradFi routes remain part of discovery and run evidence, but this project does not currently have a verified complete historical-quotation contract for those routes. They are therefore recorded as:

`BLOCKED_FULL_HISTORY_UNAVAILABLE`

A bounded latest-window response is never labeled as complete history.

## Timeframes

The project research timeframes are:

- `15m`
- `1h`
- `4h`
- `1d`

All four are derived from complete, contiguous 5-minute source bars. An incomplete parent interval is dropped rather than synthesized. This produces internally consistent multi-timeframe data and avoids conflicting independent downloads.

## Default interval

Default requested interval:

- start: `2023-01-01T00:00:00Z`
- end: start of the current UTC day, exclusive

Manual workflow dispatch can narrow the requested interval. A requested start before 2023 is clipped to the verified archive start and recorded as `effective_archive_start` in the route manifest.

## Storage format

Monthly normalized partitions are Parquet with ZSTD compression.

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
- `volume_semantics`
- `price_multiplier`
- `source_timeframe`
- `source_kind`

OHLCV numeric values are serialized as decimal strings before Parquet encoding so ingestion does not introduce binary floating-point drift.

`source_timeframe` is `5m` and `source_kind` is `gate_historical_quotation`.

## Object layout — v2

Completed calendar months:

```text
bronze/gate-history/v2/
  provider=<gateio|gateio_futures>/
    canonical=<canonical-symbol-slug>/
      market=<gate-market-slug>/
        timeframe=<15m|1h|4h|1d>/
          year=YYYY/
            month=MM/
              part-000.parquet
```

A partial month is stored as a dated snapshot instead of overwriting a completed partition:

```text
.../year=YYYY/month=MM/snapshot=YYYY-MM-DD/part-000.parquet
```

Per-route manifests:

```text
manifests/gate-history/v2/routes/
  provider=<provider>/
    canonical=<canonical-symbol-slug>/
      market=<gate-market-slug>/
        manifest.json
```

Per-run consolidated evidence:

```text
manifests/gate-history/v2/runs/<github-run-id>.json
```

The earlier experimental `v1` namespace is not qualification evidence and must not be consumed by Phase 48 backtests.

## Integrity and provenance

Each partition/route record carries or derives:

- canonical and provider market identity;
- provider type;
- price multiplier;
- timeframe;
- row count;
- first and last timestamps;
- SHA-256 of newly uploaded Parquet bytes;
- archive days found/missing;
- REST fallback-day count;
- missing 5-minute timestamps inside the observed data span;
- generation timestamp.

Existing completed monthly objects are reused unless a manual run explicitly sets `force=true`.

The pipeline never creates synthetic fill candles. Missing timestamps are evidence and remain visible in the manifest.

## Gap semantics

`missing_5m_inside_observed_span` counts missing 5-minute points only between the first and last returned source candle for a month. This avoids falsely classifying pre-listing and post-delisting time as an internal data gap.

`archive_days_missing` is a separate source-availability metric. A missing historical daily archive file can be legitimate before a market existed. Inside the most recent 30 days, REST may provide a bounded fallback; the manifest records such use explicitly.

## Workflow

Workflow:

`.github/workflows/gate-universe-full-history-to-b2.yml`

Stages:

1. **Discover** — resolve the live project universe and every Gate route.
2. **Sync** — fan out one independent matrix job per Gate route; download daily 5m archives, normalize, resample, compress and upload monthly Parquet partitions.
3. **Summarize** — collect every route summary, build consolidated run evidence and publish the run manifest to B2.

The matrix uses `fail-fast: false`: one failing route cannot erase evidence from routes that completed successfully.

## Backblaze credentials

The workflow reuses the repository's established B2 S3-compatible secrets:

- `B2_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_S3_ENDPOINT`
- `B2_BUCKET_NAME`

They are exposed only to GitHub Actions jobs. Credentials are never serialized into artifacts, manifests, Parquet files or repository content.

## Completion semantics

Supported Spot/Futures route statuses:

- `COMPLETE` — archive data transferred with no missing 5m timestamps inside observed spans;
- `COMPLETE_WITH_RECORDED_GAPS` — data transferred, with missing timestamps explicitly recorded;
- `NO_HISTORY_RETURNED` — no historical data was found for the supported route; run qualification fails;
- `ERROR` — collection, normalization or upload failed; run qualification fails.

TradFi status:

- `BLOCKED_FULL_HISTORY_UNAVAILABLE` — route is known, but complete historical transfer is deliberately blocked until its historical contract is verified.

The consolidated workflow fails if a supported route is missing a summary, reports `NO_HISTORY_RETURNED`, reports `ERROR`, or has an unexpected status. The documented TradFi limitation remains visible instead of being silently treated as complete history.

## Backtest consumption rule

Phase 48 and other qualification backtests must consume:

1. immutable completed-month objects;
2. an explicit route/run manifest;
3. a locked date range and dataset identity/fingerprint.

A current-month snapshot must not replace a previously locked OOS dataset without producing a new dataset identity. Existing dataset versioning, provenance, OOS locking, reproducibility and B2 source-snapshot controls remain authoritative.

## Operational commands

Discover the current Gate-backed project universe without B2 credentials:

```bash
python scripts/backtest/sync_gate_universe_history_to_b2.py \
  --discover-only \
  --output artifacts/gate-history-discovery.json
```

Sync one route when B2 environment variables are available:

```bash
python scripts/backtest/sync_gate_universe_history_to_b2.py \
  --canonical BTC/USDT \
  --base-asset BTC \
  --asset-class crypto \
  --provider gateio \
  --provider-symbol BTC_USDT \
  --start 2023-01-01T00:00:00Z \
  --end 2026-09-14T00:00:00Z
```

Normal production operation is the GitHub Actions workflow rather than a laptop process.
