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
Context Engine (news + events)
        ↓
Strategy Evidence / Score / Confidence / Targets
        ↓
Core Risk Engine + Portfolio Gate
        ↓
Order Preparation
        ↓
PAPER/SHADOW Execution
        ↓
Positions / Portfolio / Journal / Analytics
        ↓
Recovery / Observability / Health / Reporting
```

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
| `app/context` | news/economic-event context policy |
| `app/strategy` | evidence, scoring, confidence, strategy decisions, targets |
| `app/risk` | sizing, risk policy, trade/portfolio gates |
| `app/execution` | paper execution, pending orders, fills, atomic persistence |
| `app/position` | position lifecycle and settlement |
| `app/portfolio` | account state, exposure, correlation, portfolio constraints |
| `app/backtest` | realistic backtesting, costs, walk-forward and Monte Carlo |
| `app/research` | bounded reproducible research/optimization |
| `app/journal` | trade decision and execution journal |
| `app/analytics` | performance and risk analytics |
| `app/reporting` / `app/export_system` | report/export foundations |
| `app/recovery` | restart recovery and reconciliation |
| `app/observability` / `app/system_health_monitoring` | health, alerts, readiness and operational monitoring |
| `app/deployment_runtime` | deployment/runtime abstractions |
| `app/production_operation` | production validation and go-live checks |
| `app/live_operation` | live-operation safety and execution boundary |
| `interfaces/api` | external API boundary for clients |

## Source-of-truth rules

1. `main` is the release source of truth after a phase passes global CI and is merged.
2. Legacy phase branches are reference history only unless their code is explicitly re-reviewed and reimplemented.
3. Diverged historical branches must not be merged wholesale into `main`.
4. The global CI workflow is the merge/release quality gate.
5. Architecture documents must describe current code, not merely planned phase names.
6. Strategy, scanner, context, analytics, and assistant/presentation layers may not bypass core risk and execution boundaries.
7. Live operation remains fail-closed until a validated venue adapter is intentionally enabled.
8. Market-data consumers must use canonical data contracts and may not bypass data freshness/quality boundaries with ad-hoc provider calls.

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

Phase 37 branch verification is green: 0 mypy issues across 255 source files, 293 passing tests, and 78.66% branch-aware coverage.

## Repository governance

The code and CI source of truth is consolidated in `main`, but repository inspection from Phase 36 showed that `main` was not protected and no repository ruleset was configured. Issue #10 tracks the required repository administration policy: require pull requests and the `CI / quality` check, block force pushes/deletion, and prevent normal bypass of required checks.
