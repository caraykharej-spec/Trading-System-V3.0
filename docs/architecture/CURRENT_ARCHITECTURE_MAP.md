# Current Architecture Map

## Purpose

This document describes the implementation that exists in the active V3 release line. `main` is the release source of truth after a feature branch passes the protected `CI / quality` gate and is merged.

## Runtime flow

```text
Storm Public Markets
        ↓
type=base + settlement=usdt
        ↓
Storm Reference Universe + Storm Reference Price
        ↓
OHLCV Source Resolver
        ├──────────────→ Gate.io closest acceptable comparable market
        ├──────────────→ Yahoo Finance closest acceptable fallback
        └──────────────→ explicit NO_DATA when unresolved
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
        ├──────────────→ Assistant Analytics (read-only)
        ↓
Recovery / Observability / Health / Reporting
```

Copilot, assistant, assistant-analytics and external-model paths are explanatory/read-only. They do not own strategy, risk, portfolio or execution decisions.

## Production market-data boundary

The authoritative application source policy is:

```text
Reference universe → Storm markets where type=base and settlement=usdt
Reference price    → Storm
OHLCV primary      → Gate.io market closest to Storm reference price
OHLCV fallback     → Yahoo Finance market closest to Storm reference price
Unresolved asset   → explicit NO_DATA coverage entry
Storm OHLCV        → disabled until independently verified
```

The active market-data paths are public/no-key. Provider selection does not bypass retry, circuit breaker, freshness, OHLC integrity, outlier or reconciliation controls.

### Storm reference-universe boundary

`StormReferenceUniverseProvider` reads the public Storm `/markets` catalog and admits only records satisfying both reference-universe predicates:

```text
type       = base
settlement = usdt
```

Each admitted record carries its Storm provider symbol, canonical `BASE/USDT` identity, reference price and timestamp. Storm is therefore both the market-data universe authority and the price reference used for cross-provider matching.

Storm discovery is a data-universe operation only. A newly discovered asset does not become execution-eligible simply because it exists in Storm.

### Price-proximity OHLCV resolution

`StormDrivenUniverseResolver` resolves each Storm reference asset independently:

```text
Storm reference asset + Storm reference price
        ↓
Gate.io same-base tradable candidates
        ↓
Comparable quotes only: USDT / USDC / USD
        ↓
Fresh candidate prices
        ↓
minimum absolute percentage deviation
        ↓
inside configured tolerance?
        ├── yes → Gate.io OHLCV source
        └── no  → Yahoo Finance candidates
                         ↓
                  minimum price deviation
                         ↓
                  inside tolerance?
                    ├── yes → Yahoo OHLCV source
                    └── no  → NO_DATA
```

The default maximum accepted deviation is 5% and is configurable. The closest candidate is not accepted merely because it is the closest: it must also pass the deviation and freshness gates.

Resolution records preserve the selected provider symbol and provider price. When OHLCV is fetched, provider-specific candle symbols are normalized back to the canonical Storm `BASE/USDT` identity.

### Universe coverage reporting

Every resolver run produces a `UniverseCoverageReport` with exhaustive buckets:

```text
(reference) Storm: N
Gate.io:           G
Yahoo Finance:     Y
No Data:           U
```

The invariant is enforced:

```text
G + Y + U = N
```

The report also exposes resolved count, coverage percentage and per-asset source/reason/proximity evidence. The read-only endpoint is:

```text
GET /market-data/universe-coverage
```

No Storm asset is silently dropped because Gate.io or Yahoo Finance cannot provide an acceptable mapping.

### Gate.io REST and WebSocket

Phase 37.1 adds the real public Gate.io Spot v4 candlestick WebSocket while preserving Gate.io REST as the primary pull-based OHLCV provider:

```text
Gate.io
  ├── REST /spot/tickers
  │        ↓
  │   bulk candidate prices for Storm-price matching
  │
  ├── REST /spot/candlesticks
  │        ↓
  │   GateIOProvider
  │        ↓
  │   resolved OHLCV reads
  │
  ├── REST /spot/currency_pairs
  │        ↓
  │   GateIOSpotDiscoveryProvider
  │        ↓
  │   candidate-market metadata for Storm assets
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

Gate.io discovery no longer defines active universe membership. It supplies candidate venue markets for assets already admitted by the Storm reference-universe filter.

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
Storm   → LIVE_PRICE                              / HTTPS / public-no-key
Gate.io → OHLCV_REST + OHLCV_STREAM + DISCOVERY / HTTPS+WSS / public-no-key
Yahoo   → OHLCV_REST                              / HTTPS / public-no-key
```

The registry is descriptive/operational metadata. Universe membership and source resolution are owned by the Storm reference-universe and price-proximity contracts; the registry itself does not activate markets.

### Dynamic universe

Phase 37's generic `DynamicUniverseDiscovery` remains available as infrastructure, but the active market-data candidate authority is now Storm filtered by `type=base` and `settlement=usdt`.

Gate.io discovery is subordinate to that reference list: it finds viable provider markets for Storm assets rather than independently expanding the active data universe. Yahoo Finance is evaluated only as fallback when Gate.io has no acceptable price-matched market.

A discovered Storm asset is not automatically activated for execution. Strategy/execution eligibility still requires contract specification, risk configuration and the relevant eligibility path. Data discovery cannot expand execution authority by itself.

### OHLCV read path

For Storm-resolved assets, the intended OHLCV path is:

```text
Storm reference asset
   ↓
Storm reference price
   ↓
Gate.io candidate market selection by price proximity
   ↓ accepted
Gate.io OHLCV
   ↓
canonical BASE/USDT candles

Gate candidate unavailable / outside tolerance
   ↓
Yahoo Finance candidate selection by price proximity
   ↓ accepted
Yahoo OHLCV
   ↓
canonical BASE/USDT candles

Neither acceptable
   ↓
NO_DATA + provider-review-required evidence
```

The existing configured strategy snapshot loader continues to consume `ProductionMarketDataPlatform`. The Storm-driven resolver is exposed in composition and API without granting newly discovered assets contract/risk/execution configuration automatically.

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

Phase 38 provides a fail-closed validation boundary, and Phase 38.1 adds a separate statistical policy-calibration layer upstream of candidate qualification:

```text
Independent Historical Validation Cohort
   ↓
CalibrationObservation[]
   ↓
ThresholdCalibrator
   ├────────────→ insufficient/invalid evidence → HOLD
   ↓
CALIBRATED StrategyValidationPolicy
   ↓
Historical Candidate Data
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

Calibration and qualification have separate evidence roles. The candidate being qualified does not calibrate its own acceptance policy. An optional timezone-aware cutoff admits only calibration observations with `as_of < cutoff`, preventing future or same-boundary evidence from entering threshold estimation.

For higher-is-better metrics, Phase 38.1 takes a lower empirical quantile and applies `max(baseline minimum, empirical threshold)`. For lower-is-better metrics it takes an upper empirical quantile and applies `min(baseline maximum, empirical threshold)`. Statistical calibration can therefore tighten Phase 38 but can never loosen its existing guardrails.

Structural evidence-count requirements remain explicit baseline policy rather than statistically relaxed thresholds. Insufficient cohort size or per-metric coverage produces `HOLD` with no usable policy. Duplicate sample IDs are rejected, and every eligible cohort receives a deterministic SHA-256 fingerprint for audit/reproducibility.

`StrategyQualificationEngine.from_calibration(...)` accepts only a successful calibration report. A high score, confidence value, in-sample result, or calibration result cannot substitute for the full Phase 38 validation evidence. `CALIBRATED` and `QUALIFIED` are research/release states only; neither enables live execution.

## Trading copilot and assistant boundary

Phase 40 preserves deterministic gate evidence and exposes read-only explanations. Phases 41–42 add grounded conversation, optional external-model narration and content-free assistant telemetry. Phase 40.1 expands the evidence surface to positions, journal analytics, market change and bounded what-if simulation.

```text
DecisionEvidence + Gate Trace ─→ CopilotExplainer ─→ Structured Copilot Brief ─┐
                                                                               │
Position Repository ────────────────────────────────────────────────────────────┤
Journal Repository ─────────────────────────────────────────────────────────────┤
Live Price Provider ────────────────────────────────────────────────────────────┤
ProductionMarketDataPlatform ───────────────────────────────────────────────────┤
                                                                               ↓
                                                                    AssistantIntentRouter
                                                                               ↓
                                                              AssistantAnalyticsService / GroundingBuilder
                                                                               ↓
                                                                    EvidenceCitation[]
                                                                               ↓
                                                                    AssistantOrchestrator
                                                               ├────────→ deterministic answer
                                                               └────────→ optional ProductionLanguageModel
                                                                               ↓
                                                                  citation validation / safe fallback
```

Analytics behavior:

- `POSITIONS` reads authoritative open positions and computes read-only unrealized P&L using the existing position P&L contract;
- `JOURNAL` reads immutable completed trades and reuses existing performance analytics;
- `MARKET_CHANGE` compares the current live price with the prior completed candle close for `15m`, `1h`, `4h` and `1d` when available;
- `WHAT_IF` accepts an explicit bounded percentage scenario and computes hypothetical price/P&L effects without mutating any trading state.

When the configured universe is supplied to the assistant, analytics-only intents resolve symbols without forcing an opportunity/Copilot scan. Copilot evaluation remains lazy and is loaded only for market-brief, symbol-opportunity, rejection and risk-summary intents.

Rules:

- missing facts remain `UNKNOWN`/unavailable;
- external models receive no execution tools;
- invalid/missing citations fail closed to deterministic output;
- assistant/model failures do not alter trading decisions;
- telemetry excludes prompts, responses, evidence values, session IDs and secrets;
- what-if output is hypothetical analytics, never a forecast or trade instruction;
- assistant analytics cannot change stops, take-profit values, leverage, position size, risk budgets, orders or venue state;
- all assistant responses have no execution authority.

## Execution and live-operation boundary

The active composition root remains PAPER/SHADOW. Phase 35 provides a fail-closed live-operation framework, but no venue-specific production execution connector is enabled by default.

```text
Strategy
   ↓
Context
   ↓
Statistical Calibration Policy + Strategy Qualification
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

Phase 38.1 changes validation-policy derivation only. Phase 40.1 changes assistant-side read-only analytics only. Neither alters strategy scoring, position sizing, portfolio risk, order submission, or any live-operation gate.

## Domain ownership

| Domain | Primary responsibility |
|---|---|
| `app/universe` | Storm reference-universe discovery, provider candidate resolution, canonical instruments, mappings, eligibility and contract specs |
| `app/data` | provider registry, Gate.io REST/WSS, public price catalogs, streaming normalization, cache, historical OHLC, SLA, quality, failover, reconciliation and clock-skew evidence |
| `app/market` | indicators, trend, regime, structure, liquidity |
| `app/scanner` | scanning and opportunity generation |
| `app/context` | news/macro policy and intelligence evidence |
| `app/strategy` | evidence, scoring, confidence, strategy decisions and targets |
| `app/strategy_validation` | statistical threshold calibration, OOS, cost stress, regime/stability, forward evidence and fail-closed qualification |
| `app/risk` | sizing, trade and portfolio risk gates |
| `app/execution` | PAPER execution, pending orders, fills and atomic persistence |
| `app/position` / `app/portfolio` | position lifecycle, settlement, exposure and account state |
| `app/backtest` / `app/research` | backtesting, walk-forward, Monte Carlo and reproducible research |
| `app/copilot` | grounded read-only decision explanations |
| `app/assistant` | grounded conversation, read-only position/journal/market-change/what-if analytics, optional LLM provider/reliability and telemetry |
| `app/journal` / `app/analytics` | authoritative trade journal and performance/risk analytics |
| `app/recovery` / `app/observability` | restart/reconciliation, health and readiness |
| `app/live_operation` | fail-closed production execution safety boundary |
| `interfaces/api` | external read/control boundary, including grounded assistant query and read-only universe-coverage reporting |

## Source-of-truth rules

1. `main` is the release source of truth after protected PR merge.
2. Legacy phase branches are reference history only unless re-reviewed and reimplemented.
3. Historical diverged branches must not be merged wholesale.
4. The global protected `CI / quality` workflow is the merge/release quality gate.
5. Storm `type=base` + `settlement=usdt` markets define the reference data universe.
6. Storm defines the reference price used for provider-market matching.
7. Gate.io is the primary OHLCV resolver and must select the closest fresh comparable market inside tolerance.
8. Yahoo Finance is fallback only after Gate.io has no acceptable candidate.
9. Every unresolved Storm asset remains visible as `NO_DATA`; silent dropping is forbidden.
10. `Gate.io + Yahoo Finance + No Data` must equal the Storm reference-universe count.
11. Storm OHLCV stays disabled until independently verified.
12. Data discovery cannot auto-enable execution for newly discovered assets.
13. Statistical calibration must use an independent historical cohort and cannot weaken the Phase 38 baseline policy.
14. Insufficient calibration evidence produces `HOLD`; no downstream component may manufacture a calibrated policy from a failed report.
15. Assistant analytics must cite authoritative position, journal or market-data evidence; missing inputs stay unavailable.
16. What-if calculations are hypothetical, bounded and read-only and cannot mutate trading state or authorize execution.
17. Strategy, context, intelligence, copilot, assistant and presentation layers cannot bypass deterministic risk/execution gates.
18. Live operation remains fail-closed until a venue execution adapter is explicitly implemented, validated and enabled.

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

Phase 40.1 core feature-head validation passed: 0 mypy issues across 296 source files, 362 tests and 79.81% branch-aware coverage. The final documentation head, pull-request head and merged `main` commit must also pass the protected `CI / quality` gate before Assistant Analytics Expansion is closed.

## Repository governance

Phase 36.1 closed the remaining repository-governance gap. `main` is protected by the active `main-protection` ruleset: pull requests are required, `CI / quality` is a strict required check, branches must be up to date, force-push/non-fast-forward updates and deletion are blocked, and normal bypass is disabled.
