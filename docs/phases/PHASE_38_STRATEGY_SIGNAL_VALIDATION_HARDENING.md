# Phase 38 — Strategy & Signal Validation Hardening

## Objective

Add a fail-closed strategy qualification layer above the existing backtest/research engines so a strategy cannot be treated as production-qualified from a single in-sample or headline backtest result.

Phase 38 reuses the existing deterministic backtest, realistic cost model, walk-forward runner, Monte Carlo engine, research framework, parameter sensitivity analysis, and PAPER/SHADOW boundaries.

## Qualification evidence

A strategy qualification decision requires all of the following evidence categories:

1. chronological holdout out-of-sample performance;
2. walk-forward consistency;
3. Monte Carlo robustness;
4. execution-cost stress tolerance;
5. parameter stability across feasible research trials;
6. regime-segmented performance coverage;
7. forward PAPER/SHADOW observations.

Missing required evidence produces `HOLD`, not an implicit pass.

## Implemented modules

### `app/strategy_validation/oos.py`

Provides deterministic chronological train/validation/holdout splitting from the 15-minute anchor series and leakage-safe evaluation using the existing `BacktestEngine`.

Validation and holdout runs retain earlier historical candles only as lookback/warm-up context while `evaluation_start` prevents pre-segment trades from entering the measured result.

### `app/strategy_validation/cost_stress.py`

Runs the existing backtest engine under explicit commission, spread, slippage, and funding scenarios.

The report records return degradation and drawdown increase relative to the baseline configuration. A qualification check requires at least one actual stress scenario.

### `app/strategy_validation/regime.py`

Segments realized historical trades by explicit regime intervals and calculates per-regime:

- trade count;
- total realized P&L;
- win rate;
- profit factor.

This makes regime dependence visible instead of allowing aggregate performance to hide weak market states.

### `app/strategy_validation/stability.py`

Builds on the existing research sensitivity framework and converts objective spread into a normalized parameter-stability measure.

Qualification requires both:

- bounded normalized sensitivity;
- a configurable minimum proportion of feasible research trials.

### `app/strategy_validation/forward.py`

Defines idempotent forward PAPER/SHADOW observations with timezone-aware timestamps, risk-approval state, resolved outcome return, hit rate, mean return, and maximum consecutive losses.

Conflicting duplicate signal IDs are rejected instead of silently overwritten.

### `app/strategy_validation/qualification.py`

Implements the final `StrategyQualificationEngine`.

The gate is fail-closed and returns only:

- `QUALIFIED` when every critical evidence check passes;
- `HOLD` when evidence is missing or any critical threshold fails.

Qualification is a research/release decision. It does not enable live order submission and it does not bypass core risk, portfolio, production-readiness, or Phase 35 live-operation gates.

## Existing engines reused

Phase 38 deliberately does not create parallel backtesting/research implementations. It reuses:

- `app/backtest/engine.py`;
- `app/backtest/costs.py`;
- `app/backtest/walk_forward.py`;
- `app/backtest/monte_carlo.py`;
- `app/research/evaluator.py`;
- `app/research/sensitivity.py`;
- `app/research/models.py`.

## Default qualification policy

The default policy is intentionally configurable and represents a release gate, not a guarantee of profitability. Current defaults include minimum holdout trade count, minimum holdout profit factor, maximum drawdown, minimum profitable walk-forward ratio, Monte Carlo limits, cost-stress degradation tolerance, parameter-stability bounds, regime coverage requirements, and minimum forward PAPER/SHADOW observations.

Projects may tighten these thresholds, but downstream components may not bypass a failed qualification by changing presentation or execution code.

## Validation flow

```text
Historical Data
      ↓
Chronological Train / Validation / Holdout
      ↓
Holdout OOS Result
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

## Safety boundary

`QUALIFIED` means the strategy has satisfied the configured evidence policy. It does **not** mean live trading is activated, risk-free, or guaranteed profitable.

Live execution remains disabled/fail-closed unless all independent production and live-operation gates are intentionally satisfied and a validated venue-specific connector is configured.

## Verified CI

Initial Phase 38 implementation was validated by the global GitHub Actions quality workflow:

- compileall: PASS;
- Ruff: PASS;
- strict mypy: PASS — 0 issues in 263 source files;
- pytest: PASS — 299 tests;
- branch-aware coverage: 79.03%;
- required coverage threshold: 70%.

The final branch head must also pass the same global workflow after documentation and hardening changes, and the merged `main` commit must pass before Phase 38 is considered closed.
