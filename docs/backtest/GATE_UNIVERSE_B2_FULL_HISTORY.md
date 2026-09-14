# Gate.io Universe Full-History Research Store — Backblaze B2

Status: **RESEARCH / PAPER ONLY**

## Objective

Maintain a durable, resumable, checksum-verified and auditable OHLC research store in Backblaze B2 for every current project-universe route that is available on Gate.io and has a verified complete historical source contract.

The pipeline is isolated from execution. It does not authorize live trading, change risk limits, or change Storm's role as the reference-universe and reference-price authority.

## Universe authority

Discovery combines:

1. the live Storm reference universe (`StormReferenceUniverseProvider`);
2. `config/universe.json` as the static compatibility floor;
3. `config/market_data/source_registry.json` for explicitly qualified Gate Spot, Gate Futures and Gate TradFi routes, including configured price multipliers and symbol mappings.

When no explicit Gate Spot route exists, discovery selects a currently tradable Gate Spot market using quote priority `USDT`, then `USDC`, then `USD`.

Every Gate route is represented independently, so one canonical project symbol may retain more than one qualified Gate market route.

## Historical source policy

### Gate Historical Quotation archive — authoritative backfill source

The backfill uses Gate's public Historical Quotation service at `download.gatedata.org`.

Gate's current Historical Quotation documentation states that downloadable candlestick history is supported from **January 2023** and documents month-by-month retrieval for non-hourly data types. The v2 research store therefore uses `2023-01-01T00:00:00Z` as the default and minimum authoritative archive start.

For Spot and USDT-M Futures, the production K-line archive contract used by this project is:

```text
https://download.gatedata.org/<biz>/candlesticks_5m/YYYYMM/<market>-YYYYMM.csv.gz
```

where `biz` is:

- `spot` for Gate Spot;
- `futures_usdt` for USDT-M Futures.

The project ingests **5m** as the canonical source grain and deterministically derives the required research timeframes `15m`, `1h`, `4h` and `1d`.

Official reference:

```text
https://www.gate.com/developer/historical_quotes
```

### REST tail fallback

The Gate REST candlestick APIs are not used as the long-range archive source. They are used only as a bounded fallback for a recent unpublished archive tail, limited to the most recent 30 UTC days.

This accommodates monthly publication lag without treating REST as an unlimited history store. The fallback remains subject to Gate's public request-size limits.

### Gate TradFi

Gate's Historical Quotation interface visibly exposes a TradFi category, but the generic downloadable-path contract currently documents `spot`, `futures_usdt` and `futures_btc` business identifiers and does not provide this project with a verified programmatic TradFi historical path contract.

Accordingly, Gate TradFi routes remain present in discovery and run evidence but are fail-closed as:

`BLOCKED_FULL_HISTORY_UNAVAILABLE`

A bounded latest-window response is never labeled as complete history. TradFi can be promoted to full-history support only after a stable, reproducible archive contract is verified and covered by tests.

## Timeframes

Research timeframes stored in B2:

- `15m`
- `1h`
- `4h`
- `1d`

All four are derived from complete, contiguous 5-minute source bars. An incomplete parent interval is dropped rather than synthesized.

## Default interval

Default requested interval:

- start: `2023-01-01T00:00:00Z`
- end: start of the current UTC day, exclusive

A requested start before January 2023 is clipped to the verified archive start and recorded as `effective_archive_start` in the route manifest.

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

OHLCV values are serialized as decimal strings before Parquet encoding to avoid binary floating-point drift during ingestion.

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

A partial current month is stored as a dated snapshot:

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

## Integrity and resumability

Every candidate Parquet partition is deterministically rebuilt from the Gate source before reuse is accepted.

The pipeline computes SHA-256 for the rebuilt bytes and reads B2 object metadata with `head-object`:

- matching stored `sha256` metadata -> object is reused and counted as `reused_verified_partition_objects`;
- object exists but metadata is missing or checksum differs -> object is replaced with the verified bytes;
- object does not exist -> object is uploaded;
- `force=true` -> object is uploaded even when the checksum already matches.

This means **object existence alone is never accepted as integrity proof**.

Each route manifest records:

- canonical/provider market identity;
- price multiplier;
- requested and effective time range;
- first/last observed source timestamps;
- total 5m row count;
- route-wide missing 5m count;
- represented/missing source-day evidence;
- recent REST fallback-day count;
- source months requested/with rows/without rows;
- partition object keys and SHA-256 values;
- new/replaced/reused/forced partition counts;
- generation timestamp and integrity policy.

## Gap semantics

`missing_5m_inside_observed_span` is computed across the **entire observed route span**, not independently per month. Therefore an empty month between two populated months cannot disappear from qualification evidence.

The calculation begins at the first observed 5m candle and ends at the last observed 5m candle. Time before listing and after delisting is not automatically treated as an internal gap.

Per-partition gap counts remain available for diagnosis, while the route-level metric is authoritative for consolidated evidence.

The pipeline never creates synthetic fill candles. Missing timestamps remain visible in manifests.

## Workflow

Workflow:

`.github/workflows/gate-universe-full-history-to-b2.yml`

Stages:

1. **Discover** — resolve the live project universe and every Gate route.
2. **Sync** — fan out one independent matrix job per Gate route; retrieve monthly 5m archives, use recent REST fallback only when necessary, normalize, resample, checksum-verify and upload Parquet partitions.
3. **Summarize** — collect every route summary, build consolidated run evidence and publish the run manifest to B2.

The matrix uses `fail-fast: false`; one failing route cannot erase evidence from routes that completed successfully.

## Backblaze credentials

The workflow reuses the repository's established B2 S3-compatible secrets:

- `B2_KEY_ID`
- `B2_APPLICATION_KEY`
- `B2_S3_ENDPOINT`
- `B2_BUCKET_NAME`

They are exposed only to GitHub Actions jobs. Credentials are never serialized into artifacts, manifests, Parquet files or repository content.

## Completion semantics

Supported Spot/Futures route statuses:

- `COMPLETE` — data transferred and no route-wide 5m gap was observed;
- `COMPLETE_WITH_RECORDED_GAPS` — available data transferred and route-wide source gaps are explicitly recorded;
- `NO_HISTORY_RETURNED` — no historical data was found for a supported route; run qualification fails;
- `ERROR` — collection, normalization, verification or upload failed; run qualification fails.

TradFi status:

- `BLOCKED_FULL_HISTORY_UNAVAILABLE` — route is known but full-history transfer remains deliberately blocked until its programmatic archive contract is verified.

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
python scripts/backtest/sync_gate_universe_monthly_archive_to_b2.py \
  --discover-only \
  --output artifacts/gate-history-discovery.json
```

Sync one route when B2 environment variables are available:

```bash
python scripts/backtest/sync_gate_universe_monthly_archive_to_b2.py \
  --canonical BTC/USDT \
  --base-asset BTC \
  --asset-class crypto \
  --provider gateio \
  --provider-symbol BTC_USDT \
  --start 2023-01-01T00:00:00Z \
  --end 2026-09-14T00:00:00Z
```

Normal production operation is the GitHub Actions workflow rather than a laptop process.
