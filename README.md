# Trading-System-V3.0

A modular, rule-based trading system designed for local development in PyCharm and deployment behind an API/mobile client. The repository currently contains the validated paper/research trading core, production-operation validation, and the Phase 35 live-operation safety framework. Live execution remains disabled by default and requires an explicitly configured, venue-specific production connector plus all safety gates.

## Current status

**Phase 36 — Repository Consolidation & CI Recovery: COMPLETED**

Phase 36 has been merged into `main` and establishes `main` as the canonical source of truth. The work reconciled Phase 35, audited legacy Phase 29–35 branches, classified superseded/duplicate implementations, restored the global quality pipeline, and refreshed repository documentation to match the actual implementation.

Post-merge validation on `main` is green:

- Python compile gate: **PASS**
- Ruff lint/import-order gate: **PASS**
- Strict mypy: **PASS — 0 issues in 248 source files**
- Full pytest suite: **PASS — 285 tests**
- Branch-aware coverage: **78.24%** (required threshold: 70%)

The Phase 35 live-operation framework is now integrated into `main`. It provides activation, live-risk, execution-gateway, position-reconciliation, monitoring, incident-management, and circuit-breaker boundaries while remaining fail-closed. It does **not** enable live trading by default and it does **not** contain exchange credentials.

Repository administration note: `main` is currently not protected by a branch-protection rule or repository ruleset. The connected GitHub integration can verify this state but cannot mutate branch-protection/ruleset administration. Protection must require pull requests and the global `CI / quality` check before future merges.

See:

- `docs/architecture/CURRENT_ARCHITECTURE_MAP.md`
- `docs/phases/PHASE_36_REPOSITORY_CONSOLIDATION.md`
- `35_LIVE_TRADING_OPERATION/README.md`
- `docs/live_operation/LIVE_OPERATION_RUNBOOK.md`

## Architecture principles

- Strategy, context, risk, portfolio, execution, storage, research, operations, and presentation are separate concerns.
- Hard eligibility gates are separate from opportunity scoring and research objectives.
- Existing core risk approval remains mandatory for every execution path.
- Strategy and scanner layers do not submit production orders directly.
- Live execution is fail-closed and requires explicit production activation.
- Open-position stop-loss monitoring runs at the beginning of every trading-state cycle after restart/recovery checks.
- Realized P&L is calculated from the position's total amount/notional model, with provider-specific contract rules isolated from generic portfolio logic.
- No fixed maximum number of open positions. Portfolio limits are risk, exposure, correlation, margin, leverage, and capital constraints.
- Top 10 is a ranking presentation limit, not a trade-count limit.
- Pyth is not part of the current V3 data-source architecture.
- The core is UI-independent so the same Python domain can run from PyCharm, a server, or behind an Android-facing API.

## Implemented capability map

The repository includes these major domains:

- `app/data` — provider routing, freshness, quality, reconciliation, and reliability.
- `app/market` — indicators, trend, structure, liquidity, volatility/regime analysis.
- `app/scanner` — market scanning and opportunity generation.
- `app/context` — news/event context and trading-window policy.
- `app/strategy` — evidence, scoring, confidence, targets, and strategy integration.
- `app/risk` — sizing, policy, portfolio/trade risk, and provider-specific constraints.
- `app/execution` — paper execution, pending orders, persistence, atomic execution, fills, and risk reservation.
- `app/position` and `app/portfolio` — position lifecycle, settlement, exposure, correlation, and account state.
- `app/backtest` and `app/research` — backtesting, costs, walk-forward, Monte Carlo, and bounded research/optimization.
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

Global CI is green on the consolidated `main`. Future repository governance should enforce the same `CI / quality` job as a required merge check through branch protection/rulesets.

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

## Strategy evidence

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

## Research boundary

Research remains reproducible and controlled:

- candle datasets can be content-fingerprinted with SHA-256,
- experiment and trial identities are deterministic,
- grid and random candidate generation are bounded by `max_trials`,
- validation is explicit and can enforce a maximum generalization degradation,
- holdout data is not callable from the optimization loop,
- parameter sensitivity can be analyzed after a run,
- experiment results can be persisted idempotently in memory or SQLite.

Research never overrides strategy, risk, portfolio, execution, production-readiness, or live-operation hard gates.

## Data sources

The V3 source boundary currently contains adapters for:

- Storm
- Gate.io
- Yahoo Finance
- Public/free context sources under `app/context`

Pyth is deliberately excluded from the current V3 architecture.

The configured universe is not hard-coded by asset count; canonical instruments, provider mappings, and contract specifications are loaded from configuration.

## Safety and execution boundary

The normal composition root remains PAPER/SHADOW. Phase 35 adds a disabled-by-default production-operation framework above the existing core. A production order may only cross the Phase 35 execution gateway after environment, go-live, health, connector, core-risk, live-risk, circuit-breaker, and explicit-enable conditions are satisfied. A venue-specific production connector must still be explicitly implemented, configured, and validated before any real execution can be considered.
