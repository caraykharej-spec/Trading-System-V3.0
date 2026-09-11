# Current Architecture Map

## Purpose

This document describes the implementation that exists in the active V3 release line. `main` is the release source of truth after a feature branch passes the protected `CI / quality` gate and is merged.

## Runtime flow

```text
Provider Discovery / Canonical Universe / Symbol Mapping
        ↓
Explicit Market-Data Source Policy
        ├──────────────→ Live Price: Storm only
        └──────────────→ OHLCV: Gate.io → Yahoo Finance fallback
        ↓
Gate.io Public WebSocket + REST / Yahoo REST
        ↓
Canonical Market Events / ProviderRouter
        ↓
Cache / Historical OHLC / Freshness / Quality / SLA
        ↓
Market Analysis + Regime + Structure + Liquidity
        ↓
Market Scanner / Opportunity Pipeline
        ↓
Market Intelligence V2 → Context Engine Policy
        ↓
Strategy Evidence / Score / Confidence / Targets
        ↓
Strategy Qualification Boundary
        ↓
Core Risk Engine + Portfolio Gate
        ↓
DecisionEvidence + Gate Trace
        ├──────────────→ Copilot / Grounded Assistant / Optional LLM
        ↓
Order Preparation
        ↓
PAPER/SHADOW Execution
        ↓
Positions / Portfolio / Journal / Analytics
        ↓
Recovery / Observability / Health / Reporting
```

Copilot, assistant and external-model paths are explanatory only. They do not own strategy, risk, portfolio or execution decisions.

## Production market-data boundary

The authoritative application source policy is:

```text
Live price       → Storm only
OHLCV primary    → Gate.io
OHLCV fallback   → Yahoo Finance
Storm OHLCV      → disabled until independently verified
```

The active market-data paths are public/no-key. Provider role selection does not bypass retry, circuit breaker, freshness, OHLC integrity, outlier or reconciliation controls.

### Gate.io REST and WebSocket

Phase 37.1 adds the real public Gate.io Spot v4 candlestick WebSocket while preserving Gate.io REST as the primary pull-based OHLCV provider:

```text
Gate.io
  ├── REST /spot/candlesticks
  │        ↓
  │   GateIOProvider
  │        ↓
  │   ProviderRouter
  │
  ├── REST /spot/currency_pairs
  │        ↓
  │   GateIOSpotDiscoveryProvider
  │        ↓
  │   canonical Instrument metadata
  │
  └── WSS wss://api.gateio.ws/ws/v4/
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

The WebSocket is configured by the PAPER composition root but is opt-in. Building the application does not open a socket. `start_gateio_stream()` and `stop_gateio_stream()` own the lifecycle.

Native Gate.io OHLCV updates are not converted into artificial trade events. `CandleStreamEvent` and `CandleStreamIngestor` provide the canonical direct-candle path, including validation, duplicate rejection and per-provider/symbol/timeframe sequence protection. Existing `TradeEvent`, `MarketDataStreamIngestor` and `CandleBuilder` remain available for venues that publish trades instead of native candles.

### Time synchronization

Gate.io WebSocket `time_ms` / `time` metadata feeds `ClockSkewMonitor`:

```text
provider server timestamp
        ↓
local UTC receive timestamp
        ↓
EWMA observed offset + maximum absolute skew
        ↓
ClockSyncSnapshot / healthy-or-unhealthy evidence
```

This monitors clock drift; it does not mutate the host clock and it does not blindly trust provider time.

### Provider registry

`MarketDataProviderRegistry` records explicit capabilities:

```text
Storm   → LIVE_PRICE                          / HTTPS / public-no-key
Gate.io → OHLCV_REST + OHLCV_STREAM + DISCOVERY / HTTPS+WSS / public-no-key
Yahoo   → OHLCV_REST                          / HTTPS / public-no-key
```

The registry is descriptive/operational metadata. `source_policy.py` remains the application authority for which provider owns each read role.

### Dynamic universe

Phase 37's generic `DynamicUniverseDiscovery` remains the canonical reconciliation layer. Phase 37.1 adds an actual Gate.io discovery provider over public spot currency-pair metadata.

A discovered Gate.io market is not automatically activated for trading. Strategy/execution eligibility still requires canonical mapping, contract specification, risk configuration and universe eligibility. Discovery may expand the candidate catalog; it cannot expand execution authority by itself.

### OHLCV read path

The strategy snapshot loader now consumes `ProductionMarketDataPlatform`:

```text
read OHLCV
   ↓
hot cache
   ↓ miss
historical candle store
   ↓ miss
Gate.io REST through ProviderRouter
   ↓ failure / unsupported / invalid
Yahoo Finance fallback
   ↓
quality/freshness checks
   ↓
market analysis / strategy
```

Streaming Gate.io candles populate the same cache/history path, so push and pull data converge on canonical storage contracts.

## Market-intelligence boundary

Phase 39 processes public news and macro context before `ContextEngine`:

```text
News / Economic Events
        ↓
Normalize / Deduplicate
        ↓
Entity + Asset Relevance
        ↓
Classification / Impact / Confidence
        ↓
Canonical NewsItem / EconomicEvent
        ↓
ContextEngine
```

Market intelligence is advisory evidence. It cannot bypass ContextEngine policy, Strategy Qualification, Risk, Portfolio or Execution.

## Strategy qualification boundary

Phase 38 provides a fail-closed validation boundary:

```text
Historical Data
   ↓
Chronological Train / Validation / Holdout
   ↓
OOS + Walk Forward + Monte Carlo
   ↓
Cost Stress + Parameter Stability + Regime Coverage
   ↓
Forward PAPER / SHADOW Evidence
   ↓
StrategyQualificationEngine
   ↓
QUALIFIED / HOLD
```

A high score, confidence value or in-sample result cannot substitute for required validation evidence. `QUALIFIED` does not enable live execution.

## Trading copilot and assistant boundary

Phase 40 preserves deterministic gate evidence and exposes read-only explanations. Phases 41–42 add grounded conversation, optional external-model narration and content-free assistant telemetry.

```text
DecisionEvidence + Gate Trace
        ↓
CopilotExplainer
        ↓
Structured Copilot Brief
        ↓
AssistantIntentRouter / GroundingBuilder
        ↓
AssistantOrchestrator
   ├────────────→ deterministic grounded answer
   └────────────→ optional ProductionLanguageModel
                         ↓
                   retry / circuit breaker
                         ↓
                   citation validation
                         ↓
                 answer or safe fallback
```

Rules:

- missing facts remain `UNKNOWN`/unavailable;
- external models receive no execution tools;
- invalid/missing citations fail closed to deterministic output;
- assistant/model failures do not alter trading decisions;
- telemetry excludes prompts, responses, evidence values, session IDs and secrets;
- all assistant responses have no execution authority.

## Execution and live-operation boundary

The active composition root remains PAPER/SHADOW. Phase 35 provides a fail-closed live-operation framework, but no venue-specific production execution connector is enabled by default.

```text
Strategy
   ↓
Context
   ↓
Strategy Qualification
   ↓
Core Risk
   ↓
Portfolio Gate
   ↓
Production Readiness
   ↓
Live Risk / Circuit Breaker
   ↓
Execution Gateway
   ↓
Venue-specific connector (disabled unless explicitly implemented/validated)
```

Phase 37.1 modifies market data only. It does not add Gate.io private endpoints, balances, positions, orders, fills or order submission.

## Domain ownership

| Domain | Primary responsibility |
|---|---|
| `app/universe` | canonical instruments, Gate.io/public dynamic discovery, mappings, eligibility, contract specs |
| `app/data` | provider registry, source roles, Gate.io REST/WSS, streaming normalization, cache, historical OHLC, SLA, quality, failover, reconciliation and clock-skew evidence |
| `app/market` | indicators, trend, regime, structure, liquidity |
| `app/scanner` | scanning and opportunity generation |
| `app/context` | news/macro policy and intelligence evidence |
| `app/strategy` | evidence, scoring, confidence, strategy decisions and targets |
| `app/strategy_validation` | OOS, cost stress, regime/stability, forward evidence and qualification |
| `app/risk` | sizing, trade and portfolio risk gates |
| `app/execution` | PAPER execution, pending orders, fills and atomic persistence |
| `app/position` / `app/portfolio` | position lifecycle, settlement, exposure and account state |
| `app/backtest` / `app/research` | backtesting, walk-forward, Monte Carlo and reproducible research |
| `app/copilot` | grounded read-only decision explanations |
| `app/assistant` | grounded conversation, optional LLM provider/reliability and telemetry |
| `app/journal` / `app/analytics` | journal and performance/risk analytics |
| `app/recovery` / `app/observability` | restart/reconciliation, health and readiness |
| `app/live_operation` | fail-closed production execution safety boundary |
| `interfaces/api` | external read/control boundary for clients within allowed system modes |

## Source-of-truth rules

1. `main` is the release source of truth after protected PR merge.
2. Legacy phase branches are reference history only unless re-reviewed and reimplemented.
3. Historical diverged branches must not be merged wholesale.
4. The global protected `CI / quality` workflow is the merge/release quality gate.
5. Market-data consumers use canonical contracts and explicit provider roles.
6. Storm remains application live-price-only; Storm OHLCV stays disabled until independently verified.
7. Gate.io is primary OHLCV; Yahoo Finance is fallback.
8. Gate.io public discovery cannot auto-enable execution for newly discovered markets.
9. Strategy, context, intelligence, copilot, assistant and presentation layers cannot bypass deterministic risk/execution gates.
10. Live operation remains fail-closed until a venue execution adapter is explicitly implemented, validated and enabled.

## Current modes

- **PAPER:** supported.
- **SHADOW:** architecture-supported for observation without venue submission.
- **LIVE:** safety framework exists, but production venue execution remains disabled by default.

## Quality boundary

```text
compileall
    ↓
Ruff
    ↓
strict mypy
    ↓
full pytest
    ↓
branch-aware coverage >= 70%
```

Phase 37.1 implementation head `ac76df816ebc920bbf3b9583e7c59a85bca1845e` passed: 0 mypy issues across 292 source files, 337 tests and 78.95% branch-aware coverage. Final documentation and merged `main` must also pass the protected `CI / quality` gate before Phase 37.1 is closed.

## Repository governance

Phase 36.1 closed the remaining repository-governance gap. `main` is protected by the active `main-protection` ruleset: pull requests are required, `CI / quality` is a strict required check, branches must be up to date, force-push/non-fast-forward updates and deletion are blocked, and normal bypass is disabled.
