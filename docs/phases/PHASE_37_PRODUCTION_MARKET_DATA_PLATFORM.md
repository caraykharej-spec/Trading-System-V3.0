# Phase 37 — Production Market Data Platform

## Objective

Turn the consolidated V3 data layer into a production-oriented market-data platform without creating a second source of truth or enabling live order submission.

## Implemented capabilities

### Dynamic universe discovery

`app/universe/discovery.py` defines provider metadata discovery and deterministic reconciliation into the existing `InstrumentRegistry`.

- provider failures are isolated and reported;
- non-tradable instruments can be filtered;
- conflicting canonical metadata is surfaced rather than silently overwritten;
- the existing universe registry remains the canonical instrument model.

### Streaming ingestion boundary

`app/data/streaming.py` defines the vendor-neutral real-time trade contract.

- timezone-aware trade events;
- positive price / non-negative quantity validation;
- duplicate-event protection;
- per-provider/per-symbol sequence protection;
- transport remains behind `MarketDataStreamSource`, so a WebSocket adapter can be added without coupling strategy or scanner code to a venue SDK.

### Candle builder

`app/data/candle_builder.py` aggregates trade events into deterministic OHLCV candles.

Supported canonical timeframe units are minutes, hours, and days. Closed candles are immutable `app.data.market_data.Candle` values and can flow through the existing data-quality layer.

### Hot cache

`app/data/cache.py` provides bounded in-memory storage for live prices and recent candle series.

- live-price freshness can be enforced on reads;
- candle writes are idempotent by timestamp;
- series are bounded to prevent unbounded memory growth.

### Historical OHLC storage

`app/data/historical_store.py` provides the `CandleHistoryStore` contract and an SQLite implementation.

- idempotent `(symbol, timeframe, timestamp)` upserts;
- durable Decimal-safe OHLCV serialization;
- chronological reads with bounded limits.

### Data SLA monitoring

`app/data/sla.py` classifies market data as `HEALTHY`, `DEGRADED`, `STALE`, or `MISSING`.

This is a monitoring/readiness signal; it does not bypass existing quality or risk gates.

### Production data orchestration

`app/data/platform.py` unifies the existing `ProviderRouter` with cache, historical storage, streaming events, and candle builders.

Read path:

```text
Client / Scanner
      ↓
Hot Cache
      ↓ miss
Historical Store
      ↓ miss
ProviderRouter
      ↓
Retry / Circuit Breaker / Quality Validation / Provider Failover
      ↓
Cache + Historical Store
```

Streaming path:

```text
Venue-specific stream adapter
      ↓
MarketDataStreamIngestor
      ↓
TradeEvent validation / dedup / sequence guard
      ↓
ProductionMarketDataPlatform
      ↓
Live Price Cache + Candle Builders
      ↓
Closed Candles
      ↓
Cache + Historical Store
```

## Existing capabilities reused

Phase 37 deliberately reuses rather than duplicates:

- `app/data/provider_router.py` for REST/provider failover;
- `app/data/quality.py` for candle/live-price validation;
- `app/data/reliability.py` for retries and circuit breakers;
- `app/data/reconciliation.py` for cross-source reconciliation;
- `app/universe/registry.py` for canonical instruments.

## Explicit boundaries

Phase 37 does **not**:

- enable live trading;
- store exchange credentials;
- assume that Storm exposes a verified OHLC or WebSocket endpoint;
- add a venue-specific WebSocket client without separately validating that provider's current public API contract;
- allow streaming data to bypass strategy, risk, portfolio, or execution gates.

## Validation

Phase 37 integration tests cover:

- dynamic universe discovery with provider failure isolation;
- stream duplicate and out-of-order rejection;
- deterministic candle closure;
- live-price freshness and bounded cache behavior;
- idempotent SQLite OHLC persistence;
- SLA state classification;
- provider-to-cache/history read flow;
- streaming-to-candle persistence flow.

The global repository CI remains the required merge gate: compile, Ruff, strict mypy, full pytest, and branch-aware coverage.
