# Phase 22.5 — Architecture Hardening and Strategy Fidelity

Status: complete.

## Purpose

Phase 22.5 is a hardening pass between the Phase 22 journal/analytics work and the next feature phase. It does not add live execution. Its purpose is to remove architectural ambiguity, make the strategy evidence closer to the declared system design, tighten accounting and recovery invariants, and convert CI from a test-only signal into a real quality gate.

## Safety boundary

The application remains PAPER/SHADOW only.

- There is no live broker/exchange order submission adapter.
- Top-10 opportunities are never submitted automatically.
- Paper orders require an explicit selection handoff through `ExplicitPaperSelectionQueue`.
- `python main.py` is passive by default and performs no runtime market-data cycle.
- `python main.py cycle` is an explicit PAPER runtime action.
- Open-position stop-loss handling remains the first trading-state operation in a runtime cycle after recovery/journal reconciliation.

## Strategy fidelity

The indicator snapshot now carries the declared confirmation set used by the V3 strategy evidence layer:

- EMA 20 / 50 / 200
- SMA 50
- RSI 14
- MACD line / signal / histogram
- ATR 14
- ADX 14
- Supertrend direction
- rolling VWAP
- volume SMA
- Bollinger middle / upper / lower bands

Strategy evidence keeps hard eligibility separate from ranking. The score remains a 100-point composition with the established weights:

- HTF trend alignment: 20
- market structure: 15
- setup quality: 25
- entry confirmation: 15
- volume/liquidity: 10
- volatility quality: 5
- R:R quality: 10

The score aggregation is Decimal-safe and confidence remains an independent value.

## Risk and portfolio hardening

Pending orders now reserve quantifiable risk before new opportunities are approved. LIMIT orders can reserve risk from their requested price and structural stop. MARKET orders without a resolvable reference price are reported as unresolved rather than silently treated as zero risk.

Correlation handling uses explicit symbol-pair data. Positive correlation contributes to the correlated-risk cluster; zero or negative correlation does not create an artificial penalty. Aggregate-risk and futures-capital limits remain independent gates.

## Atomic settlement

Completed-position settlement is coordinated as one SQLite transaction across:

1. final position persistence,
2. account equity persistence,
3. account-ledger append,
4. immutable journal append.

A settlement key prevents the same closed position from applying realized P&L more than once. If a persistent write fails, the database transaction rolls back and the in-memory account equity is restored to its pre-settlement value.

Journal R-multiple uses the initial risk recorded in the decision snapshot when available instead of reconstructing a different risk amount after the trade is closed.

## Market-data reliability

Yahoo 4H data is explicitly aggregated from supported 1H bars with UTC-aligned OHLCV semantics. Session gaps can be classified as degraded quality for providers whose instruments legitimately close between sessions, while strict continuous-market validation remains available.

Provider protocols and reconciliation functions now have explicit timestamp and payload contracts. The `interfaces` package is included in setuptools discovery and is an explicit Python package, removing the source-checkout/installed-package ambiguity found after Phase 21.

## Backtest and runtime typing

The portfolio backtester no longer stores heterogeneous runtime state in untyped dictionaries. Per-symbol state is represented by a typed model containing candles, pending signal, open trades, completed trades, and rejection count.

Runtime orchestration no longer uses generic `object` placeholders for live-price callbacks, universe providers, recovery order providers, selected paper orders, or position-management results. Those boundaries are explicit `Callable` / `Iterable` contracts.

These changes make static typing verify actual architecture rather than merely annotate leaf functions.

## Application composition

`build_paper_application()` is the composition root for the local V3 application. It wires:

- canonical universe and symbol mapper,
- Storm / Gate.io / Yahoo market-data adapters,
- data-quality routers,
- strategy/context/risk/portfolio pipeline,
- SQLite repositories,
- paper executor and pending-order manager,
- restart recovery,
- atomic settlement,
- journal and analytics,
- passive health/readiness diagnostics,
- thin Android-ready API service,
- explicit paper-selection queue.

Construction itself does not perform network I/O. Network access happens only when a live price, candle request, opportunity evaluation, or explicit runtime cycle is requested.

## CI quality gate

The Phase 22.5 CI job runs, in order:

```text
Editable package install with dev dependencies
→ compileall(app, interfaces, main.py)
→ Ruff
→ mypy --strict
→ pytest with branch coverage
```

The coverage floor is 70% across `app` and `interfaces`.

A green Phase 22.5 build therefore means the repository installs, compiles, passes lint, passes strict static typing, passes the full automated test suite, and exceeds the configured coverage floor.

## Dedicated regression coverage

`tests/unit/test_phase_22_5_hardening.py` adds focused coverage for:

- extended indicator calculation and bounds,
- confirmation/liquidity sensitivity in strategy evidence,
- conservative pending-risk reservation,
- positive-cluster correlation accounting,
- journal R-multiple from recorded initial risk,
- exactly-once atomic settlement,
- rollback of all persistent settlement writes,
- Yahoo 4H OHLCV aggregation,
- session-gap degradation semantics,
- network-free PAPER composition with explicit selection.

Additional existing tests were hardened around backtesting, persistence, reconciliation, and runtime-cycle behavior.

## Final validation

The final pre-completion validation run on the fully wired branch passed every gate:

- editable package installation: passed,
- compileall: passed,
- Ruff: passed,
- strict mypy: **0 issues across 136 source files**,
- pytest: **146 passed**,
- total branch-aware coverage: **75.38%**, above the required 70% floor.

The safe `main.py` PAPER composition entrypoint and README/documentation updates were included in that green validation head.

## Completion criteria

Phase 22.5 is complete because the final implementation satisfies the architecture, safety, typing, testing, packaging, and coverage gates above. No live-execution capability is part of this phase.
