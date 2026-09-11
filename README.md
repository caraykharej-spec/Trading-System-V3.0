# Trading-System-V3.0

A modular, rule-based trading system designed for local development in PyCharm and deployment behind an API/mobile client. The repository contains the validated paper/research trading core, production-operation validation, the fail-closed Phase 35 live-operation safety framework, the Phase 37 production market-data platform, and the Phase 38 strategy/signal qualification layer. Live execution remains disabled by default and requires an explicitly configured, venue-specific production connector plus all safety gates.

## Current status

**Phase 38 — Strategy & Signal Validation Hardening: IMPLEMENTED AND CI-VALIDATED**

Phase 38 adds a fail-closed strategy qualification boundary on top of the existing backtest/research stack. Qualification requires holdout OOS evidence, walk-forward consistency, Monte Carlo robustness, execution-cost stress tolerance, parameter stability, regime coverage, and forward PAPER/SHADOW observations. Missing critical evidence produces `HOLD`, not an implicit pass.

Verified Phase 38 branch validation:

- Python compile gate: **PASS**
- Ruff lint/import-order gate: **PASS**
- Strict mypy: **PASS — 0 issues in 263 source files**
- Full pytest suite: **PASS — 299 tests**
- Branch-aware coverage: **79.03%** (required threshold: 70%)

Phase 38 does **not** enable live trading. A `QUALIFIED` strategy has only satisfied the configured research/release evidence policy; it still cannot bypass core risk, portfolio, production-readiness, connector-readiness, circuit-breaker, or Phase 35 live-operation gates.

Repository administration note: Phase 36 inspection showed that `main` was not protected by a branch-protection rule or repository ruleset. Issue #10 tracks the required policy to require pull requests and the global `CI / quality` check before future merges.

See:

- `docs/architecture/CURRENT_ARCHITECTURE_MAP.md`
- `docs/phases/PHASE_36_REPOSITORY_CONSOLIDATION.md`
- `docs/phases/PHASE_37_PRODUCTION_MARKET_DATA_PLATFORM.md`
- `docs/phases/PHASE_38_STRATEGY_SIGNAL_VALIDATION_HARDENING.md`
- `35_LIVE_TRADING_OPERATION/README.md`
- `docs/live_operation/LIVE_OPERATION_RUNBOOK.md`

## Architecture principles

- Strategy, context, risk, portfolio, execution, storage, research, validation, operations, and presentation are separate concerns.
- Hard eligibility gates are separate from opportunity scoring and research objectives.
- Existing core risk approval remains mandatory for every execution path.
- Strategy and scanner layers do not submit production orders directly.
- Strategy qualification is fail-closed and independent from live-execution activation.
- Live execution is fail-closed and requires explicit production activation.
- Market-data consumers use canonical data contracts rather than ad-hoc provider calls.
- Streaming transport is isolated behind provider contracts so venue-specific networking does not leak into scanner/strategy logic.
- Open-position stop-loss monitoring runs at the beginning of every trading-state cycle after restart/recovery checks.
- Realized P&L is calculated from the position's total amount/notional model, with provider-specific contract rules isolated from generic portfolio logic.
- No fixed maximum number of open positions. Portfolio limits are risk, exposure, correlation, margin, leverage, and capital constraints.
- Top 10 is a ranking presentation limit, not a trade-count limit.
- Pyth is not part of the current V3 data-source architecture.
- The core is UI-independent so the same Python domain can run from PyCharm, a server, or behind an Android-facing API.

## Implemented capability map

The repository includes these major domains:

- `app/universe` — canonical instruments, provider mappings, dynamic discovery, eligibility, and contract specifications.
- `app/data` — provider routing/failover, streaming ingestion, freshness, SLA, hot cache, candle building, historical OHLC persistence, quality, reconciliation, and reliability.
- `app/market` — indicators, trend, structure, liquidity, volatility/regime analysis.
- `app/scanner` — market scanning and opportunity generation.
- `app/context` — news/event context and trading-window policy.
- `app/strategy` — evidence, scoring, confidence, targets, and strategy integration.
- `app/strategy_validation` — OOS splitting, cost stress, regime analysis, parameter stability, forward PAPER/SHADOW evidence, and fail-closed strategy qualification.
- `app/risk` — sizing, policy, portfolio/trade risk, and provider-specific constraints.
- `app/execution` — paper execution, pending orders, persistence, atomic execution, fills, and risk reservation.
- `app/position` and `app/portfolio` — position lifecycle, settlement, exposure, correlation, and account state.
- `app/backtest` and `app/research` — backtesting, realistic costs, walk-forward, Monte Carlo, bounded research/optimization, and sensitivity analysis.
- `app/journal`, `app/analytics`, and `app/reporting` — journaling, analytics, export/reporting foundations.
- `app/recovery`, `app/observability`, and `app/system_health_monitoring` — recovery, reconciliation, health, alerts, and readiness monitoring.
- `app/deployment_runtime` and `app/production_operation` — deployment/runtime foundations and production validation gates.
- `app/live_operation` — Phase 35 production-operation safety boundary.

## Quality gates

The repository quality pipeline requires:

1. editable installation,
2. Python compile checks,
3. Ruff lint,
4. strict mypy over `app`, `interfaces`, and `main.py`,
5. the full pytest suite,
6. at least 70% branch-aware coverage across `app` and `interfaces`.

A phase is not complete until the feature branch and merged `main` both pass the global `CI / quality` workflow.

## Run from PyCharm or terminal

Use the project root as the working directory.

Passive local status only:

```bash
python main.py
```

or explicitly:

```bash
python main.py status
```

This builds the PAPER application, reads local state, and runs passive readiness diagnostics without starting a market-data/runtime cycle.

To explicitly run one PAPER runtime cycle:

```bash
python main.py cycle
```

The runtime may request market data, but it still cannot submit live orders. The paper-selection queue is empty unless a caller explicitly places selected PAPER orders into it; Top-10 opportunities are never auto-submitted.

Optional paths:

```bash
python main.py status --db data/trading_system_v3.db --universe config/universe.json
```

## Risk constants

The initial policy is:

- Maximum risk per trade: **1.0% of equity**
- Maximum aggregate open risk: **4.0% of equity**
- Storm-specific maximum SL loss relative to position amount: **10%**
- No fixed maximum open-position count
- Minimum R:R: **2.5**
- Minimum score: **90 / 100**
- Minimum confidence: **90%**

These are policy defaults and must be enforced by the risk/strategy layers, not scattered across UI or research code.

## Strategy evidence and qualification

The V3 analysis/evidence stack includes EMA 20/50/200, SMA 50, RSI 14, MACD, ATR 14, ADX 14, Supertrend direction, rolling VWAP, volume confirmation, and Bollinger Bands.

The opportunity score remains a 100-point ranking model after hard gates:

- HTF trend alignment: 20
- Market structure: 15
- Setup quality: 25
- Entry confirmation: 15
- Volume/liquidity: 10
- Volatility quality: 5
- R:R quality: 10

Score and confidence remain independent.

Phase 38 adds a separate qualification boundary. A high score/confidence signal or strong aggregate backtest cannot by itself qualify a strategy. Qualification evaluates independent OOS, walk-forward, Monte Carlo, cost-stress, parameter-stability, regime, and forward PAPER/SHADOW evidence.

## Research boundary

Research remains reproducible and controlled:

- candle datasets can be content-fingerprinted with SHA-256,
- experiment and trial identities are deterministic,
- grid and random candidate generation are bounded by `max_trials`,
- validation is explicit and can enforce a maximum generalization degradation,
- holdout data is not callable from the optimization loop,
- parameter sensitivity can be analyzed after a run,
- experiment results can be persisted idempotently in memory or SQLite.

Research and qualification never override strategy, risk, portfolio, execution, production-readiness, or live-operation hard gates.

## Data sources and production data boundary

The V3 source boundary currently contains adapters for:

- Storm
- Gate.io
- Yahoo Finance
- Public/free context sources under `app/context`

Pyth is deliberately excluded from the current V3 architecture.

The configured universe is not hard-coded by asset count; canonical instruments, provider mappings, and contract specifications are loaded from configuration. Phase 37 additionally defines provider metadata discovery through `DynamicUniverseDiscovery` so supported markets can be reconciled into the canonical registry when a venue-specific discovery adapter is supplied.

The production market-data read path is:

```text
Hot Cache
    ↓ miss
Historical OHLC Store
    ↓ miss
ProviderRouter
    ↓
Retry / Circuit Breaker / Quality Validation / Provider Failover
```

The streaming path is transport-neutral:

```text
Venue Stream Adapter
    ↓
MarketDataStreamIngestor
    ↓
Trade Validation / Dedup / Sequence Guard
    ↓
Candle Builders + Live Cache
    ↓
Historical OHLC Store
```

Venue-specific WebSocket clients must be implemented only against verified provider API contracts.

## Safety and execution boundary

The normal composition root remains PAPER/SHADOW. Phase 35 adds a disabled-by-default production-operation framework above the existing core. A production order may only cross the Phase 35 execution gateway after environment, go-live, health, connector, core-risk, live-risk, circuit-breaker, and explicit-enable conditions are satisfied. A venue-specific production connector must still be explicitly implemented, configured, and validated before any real execution can be considered.
