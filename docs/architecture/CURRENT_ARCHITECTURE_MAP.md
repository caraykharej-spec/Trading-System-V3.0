# Current Architecture Map

## Purpose

This document is the repository-level architecture map for the consolidated V3 system. It describes the implementation that exists in the active Phase 36 line rather than historical phase intentions.

## Runtime flow

```text
Universe / Provider Mapping
        ↓
Market Data Providers
        ↓
Freshness / Quality / Reliability / Reconciliation
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

A production connector is disabled by default. The presence of `app/live_operation` does not by itself enable real-money execution.

## Domain ownership

| Domain | Primary responsibility |
|---|---|
| `app/universe` | canonical instruments, mappings, eligibility, contract specs |
| `app/data` | providers, routing, freshness, data quality, reconciliation, reliability |
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

1. `main` is the release source of truth after Phase 36 merge.
2. Legacy phase branches are reference history only unless their code is explicitly re-reviewed and reimplemented.
3. Diverged historical branches must not be merged wholesale into `main`.
4. The global CI workflow is the merge/release quality gate.
5. Architecture documents must describe current code, not merely planned phase names.
6. Strategy, scanner, context, analytics, and assistant/presentation layers may not bypass core risk and execution boundaries.
7. Live operation remains fail-closed until a validated venue adapter is intentionally enabled.

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

Phase 36 is complete only when this pipeline is green on the consolidation line and then on `main` after merge.
