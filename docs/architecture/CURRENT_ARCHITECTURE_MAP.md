# Current Architecture Map

## Purpose

This document is the repository-level architecture map for the consolidated V3 system. It describes the implementation that exists in the active release line rather than historical phase intentions.

## Runtime flow

```text
Dynamic Universe Discovery / Provider Mapping
        ↓
REST + Streaming Market Data Providers
        ↓
Stream Validation / Dedup / Sequence Guard
        ↓
ProviderRouter Retry / Circuit Breaker / Failover
        ↓
Hot Cache / Candle Builder / Historical OHLC Store
        ↓
Freshness / SLA / Quality / Reliability / Reconciliation
        ↓
Market Analysis + Regime + Structure + Liquidity
        ↓
Market Scanner / Opportunity Pipeline
        ↓
Market Intelligence V2
        ↓
Context Engine Policy (news + macro events)
        ↓
Strategy Evidence / Score / Confidence / Targets
        ↓
Strategy Qualification Boundary
        ↓
Core Risk Engine + Portfolio Gate
        ↓
DecisionEvidence + Gate Trace
        ├──────────────→ CopilotExplainer → API / Android / Future LLM UI
        ↓
Order Preparation
        ↓
PAPER/SHADOW Execution
        ↓
Positions / Portfolio / Journal / Analytics
        ↓
Recovery / Observability / Health / Reporting
```

The copilot branch is explanatory only. It is not on the execution-authority path and cannot write back into strategy, risk, portfolio, readiness, or execution decisions.

## Market-intelligence boundary

Phase 39 adds an evidence-processing layer before the existing `ContextEngine`. The ContextEngine remains the policy owner for blocking/delay behavior.

```text
NewsProvider / Public Feeds
        ↓
RawNewsRecord
        ↓
Normalization + URL Canonicalization
        ↓
Cross-source Deduplication
        ↓
Entity / Symbol Relevance
        ↓
Category + Impact + Confidence
        ↓
Canonical NewsIntelligence
        ↓
NewsItem bridge
        ↓
ContextEngine
```

Macro events use a parallel path:

```text
EconomicEvent
    ↓
Currency / Symbol Inference
    ↓
Macro / Regulatory Classification
    ↓
Event Confidence
    ↓
Existing Critical / High Event Windows
```

Historical intelligence evidence is evaluated without introducing execution authority. Directional news can be checked against forward returns; economic events are evaluated by forward move magnitude unless an explicit directional model exists.

## Strategy qualification boundary

Phase 38 adds a release/research qualification boundary around the existing strategy, backtest, and research engines. It is not a per-order execution shortcut and it cannot activate live trading.

```text
Historical Dataset
        ↓
Chronological Train / Validation / Holdout
        ↓
Holdout OOS Performance
        ├───────────────┐
        ↓               ↓
Walk Forward      Monte Carlo
        ↓               ↓
Cost Stress       Parameter Stability
        └───────┬───────┘
                ↓
         Regime Coverage
                ↓
   Forward PAPER / SHADOW
                ↓
 StrategyQualificationEngine
                ↓
       QUALIFIED / HOLD
```

Missing required evidence or a failed critical threshold yields `HOLD`. `QUALIFIED` means only that the configured strategy-validation policy passed; core risk, portfolio, production-readiness, connector-readiness, and live-operation gates remain independently mandatory.

## Trading-copilot boundary

Phase 40 adds a read-only explanation layer over deterministic domain evidence.

```text
Strategy Result
Context Assessment
Risk Assessment
Portfolio Assessment
        ↓
DecisionEvidence + Gate Trace
        ↓
CopilotExplainer
        ↓
CopilotItemBrief / CopilotMarketBrief
        ↓
GET /assistant/brief
GET /assistant/opportunity?symbol=...
        ↓
Android / Dashboard / Future Model Narrator
```

The application pipeline now preserves symbol-level outcomes for stages that previously contributed only aggregate rejection counters:

- STRATEGY → NO_TRADE
- CONTEXT → HOLD
- RISK → REJECTED
- PORTFOLIO → REJECTED

Upstream reason strings are preserved as evidence. Copilot objects set `execution_authority = False`. A missing fact is not reconstructed from assumptions.

A future model-backed narrator must consume the structured copilot contract. It may summarize or translate evidence but may not call execution interfaces, change gate outcomes, invent prices/scores/probabilities, or transform a failed gate into a trade recommendation.

## Production market-data boundary

Phase 37 adds a production-oriented data boundary while preserving the existing canonical models and provider failover stack:

```text
Provider Metadata ──→ DynamicUniverseDiscovery ──→ InstrumentRegistry

REST Providers ─────→ ProviderRouter ─────────────┐
                                                  ├─→ ProductionMarketDataPlatform
Streaming Adapter ──→ MarketDataStreamIngestor ───┘
                                                           ↓
                                           Live Price Cache / Candle Builders
                                                           ↓
                                           SQLite Historical OHLC Store
                                                           ↓
                                             Scanner / Strategy Consumers
```

Venue-specific WebSocket implementations remain behind the `MarketDataStreamSource` protocol. No unverified Storm streaming/OHLC endpoint is assumed by the architecture.

## Production-operation boundary

Phase 35 adds a fail-closed operational boundary above the validated core:

```text
Signal Production
    ↓
Core Risk Approval
    ↓
Live Risk Controller
    ↓
Production Activation Gate
    ↓
Execution Gateway
    ↓
Venue-specific Exchange Connector
    ↓
Position Reconciliation
    ↓
Monitoring / Incidents / Operations Dashboard
```

A production execution connector is disabled by default. The presence of `app/live_operation` does not by itself enable real-money execution.

## Domain ownership

| Domain | Primary responsibility |
|---|---|
| `app/universe` | canonical instruments, dynamic discovery, mappings, eligibility, contract specs |
| `app/data` | providers, streaming ingest, routing/failover, cache, candle building, historical OHLC, SLA, quality, reconciliation, reliability |
| `app/market` | indicators, trend, regime, structure, liquidity |
| `app/scanner` | scanning and opportunity generation |
| `app/context` | news/economic-event policy plus intelligence normalization, deduplication, relevance, classification, confidence, macro enrichment, and historical impact evidence |
| `app/strategy` | evidence, scoring, confidence, strategy decisions, targets |
| `app/strategy_validation` | holdout OOS, cost stress, regime analysis, parameter stability, forward PAPER/SHADOW evidence, qualification gate |
| `app/risk` | sizing, risk policy, trade/portfolio gates |
| `app/execution` | paper execution, pending orders, fills, atomic persistence |
| `app/position` | position lifecycle and settlement |
| `app/portfolio` | account state, exposure, correlation, portfolio constraints |
| `app/backtest` | realistic backtesting, costs, walk-forward and Monte Carlo |
| `app/research` | bounded reproducible research/optimization and sensitivity analysis |
| `app/copilot` | grounded, read-only explanation of deterministic opportunity and gate evidence |
| `app/journal` | trade decision and execution journal |
| `app/analytics` | performance and risk analytics |
| `app/reporting` / `app/export_system` | report/export foundations |
| `app/recovery` | restart recovery and reconciliation |
| `app/observability` / `app/system_health_monitoring` | health, alerts, readiness and operational monitoring |
| `app/deployment_runtime` | deployment/runtime abstractions |
| `app/production_operation` | production validation and go-live checks |
| `app/live_operation` | live-operation safety and execution boundary |
| `interfaces/api` | external API boundary for clients, including read-only copilot routes |

## Source-of-truth rules

1. `main` is the release source of truth after a phase passes global CI and is merged.
2. Legacy phase branches are reference history only unless their code is explicitly re-reviewed and reimplemented.
3. Diverged historical branches must not be merged wholesale into `main`.
4. The global CI workflow is the merge/release quality gate.
5. Architecture documents must describe current code, not merely planned phase names.
6. Strategy, scanner, context, analytics, copilot, and presentation layers may not bypass core risk and execution boundaries.
7. Live operation remains fail-closed until a validated venue adapter is intentionally enabled.
8. Market-data consumers must use canonical data contracts and may not bypass data freshness/quality boundaries with ad-hoc provider calls.
9. Strategy qualification is fail-closed; a single in-sample backtest, score, or confidence value cannot substitute for the required validation evidence set.
10. Market intelligence is evidence-only. Classifier confidence or news sentiment cannot replace ContextEngine policy, strategy qualification, core risk, portfolio, or execution gates.
11. Unrelated news must remain unknown/global rather than being force-mapped to an asset.
12. Copilot output must remain grounded in recorded domain evidence; missing values must remain unavailable rather than inferred.
13. Copilot and any future LLM narrator have no execution authority and may not change `NO_TRADE`, `HOLD`, or `REJECTED` outcomes.

## Current execution modes

- PAPER: supported by the core execution stack.
- SHADOW: architecture-compatible and intended for production observation without venue submission.
- LIVE: framework exists, but a venue-specific production connector must be explicitly configured and validated; default state remains disabled.

## Quality boundary

The global quality gate covers:

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

Phase 40 implementation verification is green: 0 mypy issues across 276 source files, 310 passing tests, and 79.51% branch-aware coverage. The final documentation head and merged `main` commit must pass the workflow before Phase 40 is considered closed.

## Repository governance

The code and CI source of truth is consolidated in `main`, but repository inspection from Phase 36 showed that `main` was not protected and no repository ruleset was configured. Issue #10 tracks the required repository administration policy: require pull requests and the `CI / quality` check, block force pushes/deletion, and prevent normal bypass of required checks.
