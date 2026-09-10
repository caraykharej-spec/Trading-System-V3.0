# Phase 23 — Research / Optimization Framework

Status: complete.

## Purpose

Phase 23 adds a controlled, reproducible research layer on top of the validated V3 backtest stack. The goal is to compare approved parameter variants without allowing research code to silently weaken production risk policy, rewrite setup logic, alter scoring weights, or contaminate untouched holdout data.

This phase is analytical only. It does not submit orders and does not enable live execution.

## Architecture

```text
Immutable Dataset View
        |
        v
Dataset Fingerprint
        |
        v
ExperimentSpec
  - strategy version
  - train/validation/holdout fingerprints
  - approved parameter space
  - objective
  - constraints
  - search method / seed / trial budget
        |
        v
Controlled Parameter Policy
        |
        v
Grid or deterministic Random Search
        |
        v
Backtest / Portfolio / Walk-Forward Evaluator
        |
        v
Training + optional Validation Result
        |
        v
Constraints + Generalization Guard
        |
        v
Ranked Trial Results
        |
        +--> Sensitivity Analysis
        |
        +--> Immutable Experiment Registry
```

## Controlled parameter surface

The Phase 23 default policy is deny-by-default. The only strategy-rule parameters exposed to optimization are:

- `min_rr`
- `min_score`
- `min_confidence`

The declared system rules remain hard floors:

- `min_rr >= 2.5`
- `min_score >= 90`
- `min_confidence >= 90`

Score and confidence may not exceed 100. Research may therefore test equal or stricter eligibility thresholds, but it cannot lower the declared quality gates.

The research parameter surface deliberately does **not** expose:

- risk per trade,
- aggregate risk,
- Storm collateral-loss limits,
- futures capital limits,
- correlated-risk limits,
- scoring weights,
- setup definitions,
- stop-loss manipulation,
- live-execution settings.

Adding a future tunable requires an explicit code change to the allowlist and its validation contract; arbitrary dictionary keys are rejected.

## Reproducibility

`ExperimentSpec.experiment_id` is a deterministic SHA-256 identity over:

- framework version,
- experiment name,
- strategy version,
- training/validation/holdout dataset fingerprints,
- complete parameter space,
- objective,
- search method,
- random seed,
- trial budget,
- constraints.

`fingerprint_candles()` canonicalizes timezone-aware candle data to UTC before hashing OHLCV content. Reordering input candles does not change the fingerprint, while a market-data value change does.

Every trial also receives a deterministic ID derived from the experiment ID and canonical parameter set.

## Search methods

Two bounded search modes are supported:

### GRID

Evaluates every explicit combination. If the Cartesian product exceeds `max_trials`, the framework fails instead of silently truncating the experiment.

### RANDOM

Samples combinations without replacement using an explicit deterministic seed. Repeating the same experiment specification therefore yields the same candidate sequence. Random search samples combination indexes directly and does not materialize the entire Cartesian product in memory.

There is intentionally no uncontrolled continuous optimizer or strategy self-modification in Phase 23.

## Objectives

Supported deterministic objectives are:

- total return percent,
- win rate percent,
- return/drawdown ratio.

Return/drawdown ratio uses a minimum denominator of one percentage point to avoid division-by-zero and unstable infinite rankings.

Objectives are ranking criteria only. They do not bypass feasibility constraints.

## Constraints and overfitting controls

`ResearchConstraints` supports:

- minimum trade count,
- maximum drawdown,
- minimum profit factor,
- minimum walk-forward OOS window count,
- maximum training-to-validation objective degradation.

A trial failing any constraint is retained in experiment history with explicit violation reasons but is not eligible to become the best trial.

When a validation dataset fingerprint is declared, a validation evaluator is mandatory. When no validation fingerprint is declared, passing a validation evaluator is rejected. Training, validation, and holdout fingerprints must also be distinct. These contracts reduce ambiguous or accidentally overlapping experiment manifests.

The optional `holdout_fingerprint` is metadata only: `ExperimentRunner` has no holdout evaluator argument. The optimization loop therefore cannot touch the declared final holdout through its normal interface. Final holdout evaluation remains a separate post-selection validation action.

## Evaluators

Phase 23 provides adapters for the existing research engines:

- `BacktestResearchEvaluator`
- `PortfolioResearchEvaluator`
- `WalkForwardResearchEvaluator`

All three convert an approved `ParameterSet` into `StrategyRules` and reuse the existing V3 backtest engines. `BacktestEngine`, `PortfolioBacktestEngine`, and `WalkForwardRunner` now accept an explicit immutable `StrategyRules` object while preserving the existing defaults.

This keeps parameter research on the same strategy evaluation path instead of cloning strategy logic into a research-only implementation.

The runner also accepts the `ResearchEvaluator` protocol, so future evaluators can be added without coupling the experiment engine to a specific backtester.

## Walk-forward integration

`WalkForwardResearchEvaluator` reuses the leakage-aware Phase 22 rolling evaluation. Individual OOS windows are preserved and an aggregate summary reports:

- mean OOS return,
- worst OOS drawdown,
- aggregate trade win rate,
- aggregate profit factor,
- total trades,
- rejected signals,
- completed OOS window count.

`min_oos_windows` can reject parameter variants that appear successful with insufficient rolling validation history. When an explicit validation evaluator exists, the OOS-window constraint is enforced on validation rather than incorrectly penalizing a plain training summary.

## Dataset integrity

`fingerprint_candles()` rejects malformed research views before hashing:

- timestamps must be timezone-aware,
- a candle timeframe must match the timeframe bucket containing it,
- duplicate timestamps inside a timeframe are rejected,
- empty symbol datasets are rejected.

This makes experiment fingerprints meaningful data identities rather than hashes over ambiguous input containers.

## Sensitivity analysis

`analyze_parameter_sensitivity()` groups feasible trials by each parameter value and calculates:

- trial count,
- mean objective,
- best objective,
- worst objective,
- spread between parameter-value mean objectives.

This supports stability analysis: a parameter whose apparent edge disappears after a very small value change can be identified instead of selecting only the single highest point estimate.

## Experiment registry

Two registries are available:

- `InMemoryExperimentRegistry`
- `SQLiteExperimentRegistry`

The SQLite registry stores canonical experiment payloads in `research_experiments`. `experiment_id` is the idempotency key:

- identical replay is a no-op,
- the same ID with a different result payload is a data-integrity conflict.

Stored payloads include dataset identities, strategy version, search settings, all constraints, parameter definitions, all trials, training/validation summaries, per-window summaries, objective values, validation degradation, feasibility, violations, and selected best-trial ID.

Research storage is independent from the trading decision path and cannot cause an order to be submitted.

## Safety invariants

Phase 23 preserves all established system invariants:

1. research cannot reduce R:R below 2.5;
2. research cannot reduce score below 90;
3. research cannot reduce confidence below 90;
4. research cannot alter the 1% per-trade or 4% aggregate risk policy;
5. research cannot move a structural stop to manufacture eligibility;
6. Top-10 opportunities remain a presentation/ranking concept;
7. no fixed open-position count is introduced;
8. Pyth remains excluded;
9. execution remains PAPER/SHADOW;
10. no live broker/exchange adapter is added.

## Dedicated regression coverage

Dedicated Phase 23 regression tests cover:

- deny-by-default parameter policy,
- prevention of weaker strategy gates,
- bounded grid search,
- deterministic random search,
- bounded-memory random sampling over a 100,000,000-combination parameter space,
- data fingerprint reproducibility,
- duplicate/misfiled candle rejection,
- dataset-partition identity separation,
- deterministic experiment identity,
- train/validation consistency,
- proportional validation degradation including negative objectives,
- OOS validation-window constraints,
- best-trial selection,
- SQLite registry idempotency, complete payload persistence, and conflict behavior,
- parameter sensitivity reporting,
- Backtest strategy-rule injection,
- Walk-Forward OOS aggregation,
- Portfolio Backtest strategy-rule injection.

## Final validation

The final implementation head passed the complete repository quality gate in GitHub Actions run `34490818557`, job `102916775806`:

- editable package installation: passed,
- compileall: passed,
- Ruff: passed,
- strict mypy: **0 issues across 145 source files**,
- pytest: **163 passed**,
- total branch-aware coverage: **76.66%**, above the required 70% floor.

The final hardening pass specifically corrected random-search memory scaling, dataset-partition identity checks, malformed candle fingerprinting, OOS-window constraint placement, negative-objective degradation math, and completeness of persisted experiment provenance.

## Completion criteria

Phase 23 is complete because the controlled optimization surface, reproducibility contracts, validation/overfitting guards, shared backtest integration, sensitivity analysis, persistence, documentation, and automated quality gates have all been implemented and validated. No live-execution capability is part of this phase.
