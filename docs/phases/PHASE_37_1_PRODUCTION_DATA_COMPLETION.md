# Phase 37.1 — Production Data Completion

## Status

**COMPLETED — IMPLEMENTED, CI-VALIDATED, AND LIVE-PUBLIC-DATA SMOKE-VALIDATED**

Phase 37.1 completes the missing venue-specific public market-data path identified after Phase 37. It does not add private venue access, account access, order submission, credentials, or live-execution authority.

## Production source policy

The application source policy remains explicit and unchanged:

```text
Live price       → Storm only
OHLCV primary    → Gate.io
OHLCV fallback   → Yahoo Finance
Storm OHLCV      → disabled until independently verified
```

All three active market-data paths are public/no-key. Phase 37.1 adds no market-data secret or credential.

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

`websocket-client` is the only new runtime dependency and is isolated behind the Gate.io stream adapter.

## Live public connectivity evidence

Phase 37.1 also contains a non-required external smoke test:

- workflow: `.github/workflows/gateio-public-smoke.yml`
- script: `scripts/market_data/gateio_public_smoke.py`
- production endpoint: `wss://api.gateio.ws/ws/v4/`
- public channel: `spot.candlesticks`
- validation subscription: `BTC_USDT`, `15m`
- credentials/API key: **none**

GitHub Actions run `34591987373`, job `103239140783`, connected to the real Gate.io public production WebSocket and completed successfully. The runner received the subscription acknowledgement and a valid live candlestick update. The job log recorded:

```text
Gate.io public WebSocket smoke: PASS
channel=spot.candlesticks pair=BTC_USDT timeframe=15m
```

The smoke workflow is deliberately **not** a required `main` quality check. It remains manually dispatchable so a temporary external Gate.io/network outage cannot incorrectly mark repository code quality as failed. The protected `CI / quality` workflow remains deterministic and required for every merge.

## Canonical candle events

Phase 37.1 extends `app/data/streaming.py` with `CandleStreamEvent`, `CandleMarketDataStreamSource` and `CandleStreamIngestor` so a venue that publishes native OHLCV does not need to be converted into synthetic trade events first.

`ProductionMarketDataPlatform.ingest_candle()` performs idempotent cache/history updates. Existing trade-event ingestion and `CandleBuilder` remain available for providers that expose trades instead of native candles.

## Time synchronization

`app/data/time_sync.py` adds `ClockSkewMonitor`. Gate.io WebSocket `time_ms`/`time` values are compared with the local UTC receive timestamp and recorded as a bounded EWMA offset plus maximum observed absolute skew.

This is monitoring evidence, not local-clock mutation. A provider timestamp can therefore be flagged as unhealthy without changing the host clock or trusting the provider blindly.

## Provider registry

`app/data/provider_registry.py` defines explicit provider roles:

- `LIVE_PRICE`
- `OHLCV_REST`
- `OHLCV_STREAM`
- `DISCOVERY`

The default registry declares:

```text
Storm   → LIVE_PRICE                            / HTTPS     / public-no-key
Gate.io → OHLCV_REST, OHLCV_STREAM, DISCOVERY / HTTPS+WSS / public-no-key
Yahoo   → OHLCV_REST                            / HTTPS     / public-no-key
```

This registry describes responsibilities and transport capabilities. It does not bypass `source_policy.py`, `ProviderRouter`, quality checks or failover.

## Gate.io dynamic universe discovery

`app/universe/gateio_discovery.py` implements public Gate.io Spot discovery through `/spot/currency_pairs` and normalizes provider metadata into canonical `Instrument` objects, including:

- base/quote assets,
- tradability,
- minimum base quantity,
- amount precision → quantity step,
- price precision → price tick.

Discovery is deliberately separate from activation. A market discovered at Gate.io is **not automatically tradable by Strategy or Execution**. Activation still requires the repository's canonical symbol mapping, contract specification, risk policy and eligibility/configuration path.

## Application composition

`PaperApplication` exposes:

- `provider_registry`,
- `market_data_platform`,
- `gateio_candle_stream`,
- `gateio_candle_ingestor`,
- `gateio_discovery`,
- explicit `start_gateio_stream()` / `stop_gateio_stream()` lifecycle.

The strategy snapshot loader reads OHLCV through `ProductionMarketDataPlatform`, allowing the path:

```text
Gate WebSocket updates
       ↓
cache/history
       ↓
strategy snapshot read
       ↓ cache/history miss
Gate.io REST
       ↓ failure/unsupported/invalid
Yahoo Finance fallback
```

Storm remains the only application live-price source.

## Deterministic validation

Global CI on implementation head `ac76df816ebc920bbf3b9583e7c59a85bca1845e`:

- compile: PASS
- Ruff: PASS
- strict mypy: PASS — 0 issues in 292 source files
- full pytest: PASS — 337 tests
- branch-aware coverage: 78.95% (required threshold 70%)

The protected PR #27 passed PR-triggered `CI / quality` and merged to `main` as commit `5a589b667d8855e8d326166a13aa3339b8bdca1a`. Post-merge `main` `CI / quality` also passed.

Deterministic CI tests validate parsing, canonical normalization, discovery metadata, source-role registry, clock skew, duplicate/out-of-order rejection and persistence into cache/history without depending on external Gate.io uptime. The separate smoke workflow supplies external production-connectivity evidence.

## Deliberate boundaries

Phase 37.1 does **not** add:

- Gate.io private/authenticated APIs,
- balances, positions, orders or fills,
- Gate.io execution,
- Storm OHLCV,
- automatic activation of every discovered Gate.io market,
- live trading.

The production Gate.io socket implementation is real and live-connectivity-validated, but the normal application remains PAPER/SHADOW and the socket is opt-in. Venue execution remains a later, separately gated concern.

## Acceptance criteria

Phase 37.1 is complete because:

1. the actual public Gate.io Spot candlestick WebSocket adapter exists behind a canonical contract;
2. native candle events are normalized and protected from duplicates/out-of-order delivery;
3. streamed candles update the Phase 37 cache/history platform;
4. provider timestamp skew is monitored;
5. Gate.io public spot discovery is implemented without credentials;
6. provider responsibilities are registered explicitly;
7. Storm/Gate/Yahoo source ownership remains unchanged;
8. protected PR and post-merge `main` `CI / quality` are green;
9. a real no-key GitHub Actions smoke run connected to Gate.io production and received a valid public candle update;
10. no private venue or live-execution path is introduced.
