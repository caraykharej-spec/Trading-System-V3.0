# Current Architecture Map

## Purpose

This document is the repository-level architecture map for the consolidated V3 system. It describes the implementation that exists in the active release line rather than historical phase intentions.

## Runtime flow

```text
Dynamic Universe Discovery / Provider Mapping
        ↓
Explicit Market-Data Source Policy
        ├──────────────→ Live Price: Storm only
        └──────────────→ OHLCV: Gate.io → Yahoo Finance fallback
        ↓
ProviderRouter Retry / Circuit Breaker / Quality Validation
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
        ├──────────────→ CopilotExplainer
        │                       ↓
        │              Structured Copilot Brief
        │                       ↓
        │              Assistant Orchestrator
        │                ├─────────────→ Deterministic Answer
        │                └─────────────→ ProductionLanguageModel
        │                                      ↓
        │                           Retry / Circuit Breaker
        │                                      ↓
        │                           OpenAIResponsesModel
        │                                      ↓
        │                           Citation / Output Validation
        │                                      ↓
        │                              API / Android / UI
        ↓
Order Preparation
        ↓
PAPER/SHADOW Execution
        ↓
Positions / Portfolio / Journal / Analytics
        ↓
Recovery / Observability / Health / Reporting
```

The copilot/assistant/model-provider branch is explanatory only. It is not on the execution-authority path and cannot write back into strategy, risk, portfolio, readiness, or execution decisions.

## Market-data source boundary

Phase 42 makes provider ownership explicit at the composition root:

```text
Live price
    ↓
Storm
    ↓
Freshness / price-quality validation
    ↓
Runtime / risk / PAPER execution consumers

OHLCV
    ↓
Gate.io (primary)
    ↓ failure / unsupported / invalid
Yahoo Finance (fallback)
    ↓
Freshness / candle-integrity / outlier validation
    ↓
Market analysis / strategy
```

Rules:

- Storm is the configured application live-price source.
- Gate.io is the primary OHLCV source.
- Yahoo Finance is the OHLCV fallback.
- Storm OHLCV remains disabled until its candle endpoint/contract is independently verified.
- The role policy fails closed if a configured required provider is missing.
- Provider role selection does not bypass the existing `ProviderRouter` retry, circuit-breaker, freshness, OHLC integrity, and outlier checks.

The broader Phase 37 streaming/data-platform abstractions remain available behind canonical contracts:

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
```

The application pipeline preserves symbol-level outcomes for stages that previously contributed only aggregate rejection counters:

- STRATEGY → NO_TRADE
- CONTEXT → HOLD
- RISK → REJECTED
- PORTFOLIO → REJECTED

Upstream reason strings are preserved as evidence. Copilot objects set `execution_authority = False`. A missing fact is not reconstructed from assumptions.

## Grounded assistant and production LLM boundary

Phase 41 defines the grounded conversation contract. Phase 42 adds an optional production provider runtime above that contract without expanding authority.

```text
User Query
    ↓
AssistantIntentRouter
    ↓
Fresh CopilotMarketBrief
    ↓
GroundingBuilder
    ↓
EvidenceCitation[]
    ↓
AssistantOrchestrator
    ├──────────────→ Deterministic grounded response
    │
    └──────────────→ ProductionLanguageModel
                              ↓
                 Retry / Circuit Breaker / Telemetry
                              ↓
                    OpenAIResponsesModel
                              ↓
                         ModelReply
                              ↓
                Citation / instruction validator
                     ↓                ↓
                  accept           reject
                     ↓                ↓
                model answer    deterministic fallback
```

The production model path is disabled by default. Enabling it requires environment-backed configuration and an external API key. `OpenAIResponsesModel` uses the bounded `ModelPrompt` contract and receives no execution tools/callbacks.

Production safeguards include:

- explicit enable flag,
- provider/model allowlist validation,
- prompt-character budget,
- output-token budget,
- request timeout,
- bounded retry/backoff,
- circuit breaker,
- Phase 41 citation/output validation,
- deterministic fallback on provider/model failure,
- no execution authority.

Model/network CI tests use injected transports; CI does not require or expose a real external API secret.

### Assistant observability

`AssistantTelemetry` records bounded operational metadata only:

- provider,
- model,
- prompt-version identifier,
- success/failure outcome,
- latency,
- evidence count,
- output character count,
- reported input/output token counts,
- error type,
- UTC event time.

It deliberately excludes:

- API keys or other secrets,
- prompt/query text,
- model-response text,
- evidence values,
- session IDs.

Read-only observability endpoint:

```text
GET /assistant/metrics
```

It returns aggregate calls, successes, failures, token counts and average latency. Conversation/query behavior remains on:

```text
POST /assistant/query
```

Every `AssistantResponse` retains `execution_authority = False`.

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
| `app/data` | explicit source roles, providers, streaming ingest, routing/failover, cache, candle building, historical OHLC, SLA, quality, reconciliation, reliability |
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
| `app/assistant` | grounded conversation routing, citations, bounded sessions, provider/runtime policy, LLM adapter, reliability and assistant telemetry |
| `app/journal` | trade decision and execution journal |
| `app/analytics` | performance and risk analytics |
| `app/reporting` / `app/export_system` | report/export foundations |
| `app/recovery` | restart recovery and reconciliation |
| `app/observability` / `app/system_health_monitoring` | health, alerts, readiness and operational monitoring |
| `app/deployment_runtime` | deployment/runtime abstractions |
| `app/production_operation` | production validation and go-live checks |
| `app/live_operation` | live-operation safety and execution boundary |
| `interfaces/api` | external API boundary for clients, including copilot, grounded assistant and assistant metrics routes |

## Source-of-truth rules

1. `main` is the release source of truth after a phase passes global CI and is merged.
2. Legacy phase branches are reference history only unless their code is explicitly re-reviewed and reimplemented.
3. Diverged historical branches must not be merged wholesale into `main`.
4. The global CI workflow is the merge/release quality gate.
5. Architecture documents must describe current code, not merely planned phase names.
6. Strategy, scanner, context, analytics, copilot, assistant, LLM provider, and presentation layers may not bypass core risk and execution boundaries.
7. Live operation remains fail-closed until a validated venue adapter is intentionally enabled.
8. Market-data consumers must use canonical data contracts and the explicit source-role policy; application live price is Storm-only and OHLCV is Gate.io with Yahoo fallback.
9. Storm OHLCV must remain disabled until the candle endpoint/contract is independently verified.
10. Strategy qualification is fail-closed; a single in-sample backtest, score, or confidence value cannot substitute for the required validation evidence set.
11. Market intelligence is evidence-only. Classifier confidence or news sentiment cannot replace ContextEngine policy, strategy qualification, core risk, portfolio, or execution gates.
12. Unrelated news must remain unknown/global rather than being force-mapped to an asset.
13. Copilot output must remain grounded in recorded domain evidence; missing values must remain unavailable rather than inferred.
14. Copilot and assistant/LLM narration have no execution authority and may not change `NO_TRADE`, `HOLD`, or `REJECTED` outcomes.
15. LLM output must cite only evidence supplied for the current request; invalid or missing provenance causes fail-closed fallback.
16. Conversation memory is contextual convenience only and must never replace a fresh read of deterministic trading evidence.
17. External-model secrets are environment-only and must never be committed.
18. Assistant telemetry must remain content-free and must not persist prompt text, model output, evidence values, session IDs or secrets.

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

Phase 42 implementation verification is green: 0 mypy issues across 288 source files, 329 passing tests, and 79.42% branch-aware coverage. The final documentation head and merged `main` commit must pass the workflow before Phase 42 is considered closed.

## Repository governance

The code and CI source of truth is consolidated in `main`, but repository inspection from Phase 36 showed that `main` was not protected and no repository ruleset was configured. Issue #10 tracks the required repository administration policy: require pull requests and the `CI / quality` check, block force pushes/deletion, and prevent normal bypass of required checks.
