# Phase 37.1 — Production Data Completion

## Status

**COMPLETED — IMPLEMENTED, CI-VALIDATED, AND LIVE-PUBLIC-DATA SMOKE-VALIDATED**

Phase 37.1 completes the missing venue-specific public market-data path identified after Phase 37. Phase 37.1.1 further hardens the universe/source-resolution contract so Storm is authoritative for market-data universe membership and reference prices. It does not add private venue access, account access, order submission, credentials, or live-execution authority.

## Production source policy

The authoritative market-data policy is now:

```text
Reference universe → Storm markets filtered by type=base and settlement=usdt
Reference price    → Storm
OHLCV primary      → Gate.io candidate with closest acceptable price to Storm
OHLCV fallback     → Yahoo Finance candidate with closest acceptable price to Storm
No acceptable data → explicit NO_DATA report entry
Storm OHLCV        → disabled until independently verified
```

All active market-data paths are public/no-key. Phase 37.1 adds no market-data secret or credential.

## Storm-driven universe and OHLCV resolution

`app/universe/storm_discovery.py` defines `StormReferenceUniverseProvider`. It reads the public Storm `/markets` catalog and admits only records where:

```text
type       = base
settlement = usdt
```

Each admitted market becomes a `StormReferenceAsset` with a canonical `BASE/USDT` identity, the original Storm provider symbol, the Storm reference price and timestamp.

`app/universe/market_data_resolution.py` defines `StormDrivenUniverseResolver`. Gate.io discovery is no longer an independent source of active universe membership. Instead it is used to answer: "which Gate.io market best represents this Storm reference asset?"

For each Storm reference asset the resolver:

1. finds tradable Gate.io spot candidates with the same base asset and a comparable quote (`USDT`, `USDC`, or `USD`);
2. reads Gate.io spot prices from one public `/spot/tickers` catalog request;
3. calculates absolute percentage deviation from the Storm reference price;
4. selects the closest fresh Gate.io candidate only if the deviation is inside the configured tolerance;
5. otherwise evaluates Yahoo Finance candidates (`BASE-USD`, `BASE-USDT`, `BASE-USDC`) with the same price-proximity rule;
6. if neither provider has an acceptable candidate, preserves the asset as `NO_DATA` instead of silently dropping it.

The default maximum accepted price deviation is 5% and is configurable in the resolver. Candidate prices also pass a freshness gate before they may be selected.

A selected provider symbol is used for OHLCV retrieval, but returned candles are normalized back to the canonical Storm `BASE/USDT` symbol so downstream consumers are provider-neutral.

## Universe coverage reporting

Every resolution run produces `UniverseCoverageReport` with these required buckets:

```text
(reference) Storm: <count>
Gate.io:           <count>
Yahoo Finance:     <count>
No Data:           <count>
```

The invariant is enforced in code:

```text
Gate.io + Yahoo Finance + No Data = Storm Reference Universe
```

The report also contains `resolved`, `coverage_percent`, generation time and a per-asset resolution record containing Storm reference price, selected source, selected provider symbol, selected provider price, percentage price deviation and the fallback/rejection reason.

The read-only application API exposes the report through:

```text
GET /market-data/universe-coverage
```

`PaperApplication.resolve_market_data_universe()` exposes the same operation directly to application clients. Network I/O remains lazy: constructing `PaperApplication` does not contact Storm, Gate.io or Yahoo.

This data-universe resolution does **not** automatically grant strategy/risk/execution eligibility. A newly discovered Storm asset still requires explicit contract/risk configuration before it can enter an execution path.

## Gate.io public WebSocket

`app/data/providers/gateio_stream.py` implements the verified Gate.io Spot v4 production WebSocket boundary:

```text
wss://api.gateio.ws/ws/v4/
        ↓
spot.candlesticks
        ↓
GateIOWebSocketCandleSource
        ↓
CandleStreamEvent
        ↓
CandleStreamIngestor
        ↓
ProductionMarketDataPlatform
        ├──→ MarketDataCache
        └──→ CandleHistoryStore
```

The adapter uses only public candlestick subscriptions. It includes bounded reconnect/backoff, clean start/stop lifecycle, canonical symbol/timeframe mapping, provider timestamp capture, duplicate protection and out-of-order protection. The stream is **opt-in**: building `PaperApplication` configures the source but does not open a socket or perform network I/O.

`websocket-client` is isolated behind the Gate.io stream adapter.

## Live public connectivity evidence

Phase 37.1 contains a non-required external smoke test:

- workflow: `.github/workflows/gateio-public-smoke.yml`
- script: `scripts/market_data/gateio_public_smoke.py`
- production endpoint: `wss://api.gateio.ws/ws/v4/`
- public channel: `spot.candlesticks`
- validation subscription: `BTC_USDT`, `15m`
- credentials/API key: **none**

GitHub Actions run `34591987373`, job `103239140783`, connected to the real Gate.io public production WebSocket and completed successfully. The job log recorded:

```text
Gate.io public WebSocket smoke: PASS
channel=spot.candlesticks pair=BTC_USDT timeframe=15m
```

The smoke workflow is deliberately **not** a required `main` quality check. A temporary external provider/network outage must not incorrectly mark deterministic repository quality as failed. The protected `CI / quality` workflow remains required for every merge.

## Canonical candle events

Phase 37.1 extends `app/data/streaming.py` with `CandleStreamEvent`, `CandleMarketDataStreamSource` and `CandleStreamIngestor` so a venue that publishes native OHLCV does not need to be converted into synthetic trade events first.

`ProductionMarketDataPlatform.ingest_candle()` performs idempotent cache/history updates. Existing trade-event ingestion and `CandleBuilder` remain available for providers that expose trades instead of native candles.

## Time synchronization

`app/data/time_sync.py` adds `ClockSkewMonitor`. Gate.io WebSocket `time_ms`/`time` values are compared with the local UTC receive timestamp and recorded as a bounded EWMA offset plus maximum observed absolute skew.

This is monitoring evidence, not local-clock mutation.

## Provider registry

`app/data/provider_registry.py` defines explicit provider roles:

- `LIVE_PRICE`
- `OHLCV_REST`
- `OHLCV_STREAM`
- `DISCOVERY`

The registry describes transport capabilities. Runtime universe authority and source resolution are governed by the Storm-driven resolver described above, not by independent provider discovery.

## Deterministic validation

Phase 37.1.1 branch CI on implementation head `25f6a9642e7621090e61853607533912dc0f1910`:

- compile: PASS
- Ruff: PASS
- strict mypy: PASS — 0 issues in 294 source files
- full pytest: PASS — 343 tests
- branch-aware coverage: 79.49% (required threshold 70%)

New deterministic tests verify:

- exact Storm `type=base` / `settlement=usdt` membership filtering;
- exhaustive coverage buckets;
- closest-price Gate.io selection across multiple candidate quotes;
- rejection of non-comparable quotes;
- Gate.io price-mismatch fallback to Yahoo Finance;
- explicit unresolved/no-data reporting;
- selected-source OHLCV retrieval with canonical symbol restoration;
- API serialization of Storm/Gate/Yahoo/no-data counts.

## Deliberate boundaries

Phase 37.1 does **not** add:

- Gate.io private/authenticated APIs,
- balances, positions, orders or fills,
- Gate.io execution,
- Storm OHLCV,
- automatic execution eligibility for every Storm-discovered asset,
- live trading.

The normal application remains PAPER/SHADOW. Venue execution remains a later, separately gated concern.

## Acceptance criteria

Phase 37.1/37.1.1 is complete when:

1. Storm is the explicit reference universe using `type=base` and `settlement=usdt`;
2. Storm is the reference-price authority for cross-provider market selection;
3. Gate.io selects the closest fresh comparable market inside a configured tolerance;
4. Yahoo Finance is used only after Gate.io has no acceptable market;
5. unresolved assets remain visible as `NO_DATA`;
6. the report invariant `Gate.io + Yahoo + No Data = Storm` is enforced;
7. resolved provider symbols can fetch OHLCV and return canonical Storm symbols;
8. the read-only coverage report is available through the API;
9. deterministic CI is green and protected-branch rules are satisfied;
10. no private venue or live-execution authority is introduced.
