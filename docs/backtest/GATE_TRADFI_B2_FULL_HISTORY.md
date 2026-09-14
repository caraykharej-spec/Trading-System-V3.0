# Gate TradFi Full-History Backfill to Backblaze B2

## Purpose

This pipeline extends the Gate historical-data archive contract to project routes mapped to `gateio_tradfi`. It uses Gate's public TradFi K-line REST contract and stores deterministic research partitions in the same versioned Gate data lake used by Spot and USDT-M Futures.

## Source contract

- Source: Gate public API v4
- Endpoint: `GET /tradfi/symbols/{symbol}/klines`
- Authentication: none
- Pagination bound: 500 K-lines per response
- Project route registry: `config/market_data/source_registry.json`
- Native research timeframes requested: `15m`, `1h`, `4h`, `1d`
- Pagination: newest-to-oldest using `end_time`, moving the cursor to one second before the earliest returned candle until Gate returns an empty page

The collector discovers the actual earliest timestamp returned by Gate. It does not assume a universal listing date and does not invent history before the source begins.

## Normalization and validation

Every candle is normalized to UTC and mapped back to the canonical project symbol. Route-specific price multipliers are applied explicitly. The collector rejects:

- timestamps not aligned to the requested interval;
- invalid or inconsistent OHLC values;
- conflicting duplicate timestamps;
- pagination that does not move backward;
- a route/timeframe for which Gate returns no history;
- a run with missing, unknown, or error route summaries.

Gate TradFi K-lines do not provide a research volume field in this contract. Stored partitions therefore use null volume with `volume_semantics=not_provided_by_gate_tradfi_kline` rather than synthesizing volume.

## Gap policy

Market-session gaps, weekends, exchange holidays, trading halts, and source-native missing periods are preserved. No OHLC forward-fill or synthetic bars are generated.

## Storage contract

Data partitions:

```text
bronze/gate-history/v2/
  provider=gateio_tradfi/
  canonical=<canonical-symbol>/
  market=<gate-symbol>/
  timeframe=<15m|1h|4h|1d>/
  year=YYYY/month=MM/part-000.parquet
```

Route manifests:

```text
manifests/gate-history/v2/routes/
  provider=gateio_tradfi/
  canonical=<canonical-symbol>/
  market=<gate-symbol>/manifest.json
```

Consolidated run manifests:

```text
manifests/gate-history/v2/runs/<github-run-id>-tradfi.json
```

Partitions are Parquet with ZSTD compression. Every object is rebuilt deterministically and hashed with SHA-256. Existing B2 objects are reused only when their stored SHA-256 metadata matches the newly generated artifact. New or changed objects are uploaded and then verified again through B2 object metadata.

## Resumability and rate limiting

The workflow is idempotent and route-partition aware. HTTP 429 and transient 5xx/network failures are retried with exponential backoff. Route jobs use bounded concurrency and an inter-request delay to avoid aggressive use of the public API. A failed route can be re-run without invalidating verified objects from successful routes.

## Acceptance criteria

A Gate TradFi run is accepted only when:

1. discovery returns every current `gateio_tradfi` route in the project universe;
2. every discovered route returns all four required native timeframes;
3. every route summary is `COMPLETE`;
4. there are zero `ERROR`, unknown, or missing route summaries;
5. all recorded Parquet objects have deterministic SHA-256 evidence;
6. the consolidated run manifest is published to B2.

A successful GitHub Actions job alone is not sufficient evidence if the consolidated manifest or B2 integrity checks are absent.
