# Phase 23 — Research / Optimization Framework

Status: complete.

## Purpose

Phase 23 adds a reproducible and bounded research framework for testing parameter hypotheses without mutating production strategy/risk state or repeatedly peeking at final out-of-sample data.

The framework is designed for PAPER/RESEARCH use only. It does not enable live execution.

## Core invariants

1. Parameter spaces are finite, explicit and bounded.
2. GRID search must cover its full declared space; it may not silently truncate combinations.
3. RANDOM search is deterministic for a declared seed and samples without replacement.
4. Every experiment declares `strategy_version` and `data_version` provenance.
5. Candidate selection uses TRAIN + VALIDATION only.
6. Final OOS is evaluated exactly once for the selected candidate and never participates in selection.
7. Undefined objectives are rejected rather than converted into invented numeric values.
8. Research constraints are hard eligibility rules, separate from the optimization objective.
9. Experiment and trial metadata can be persisted immutably.
10. The framework does not mutate global strategy constants, risk policy or module state.

## Architecture

```text
ExperimentSpec
    |
    +-- strategy_version
    +-- data_version
    +-- seed
    +-- objective
    +-- hard research constraints
    |
ParameterSpace
    |
    +-- finite ParameterSpec values
    +-- GRID or seeded RANDOM enumeration
    +-- combination safety limit
    |
ResearchRunner
    |
    +-- TRAIN evaluation
    +-- TRAIN constraints
    +-- VALIDATION evaluation
    +-- VALIDATION constraints
    +-- deterministic ranking
    |
Selected parameter set
    |
    +-- exactly one sealed OOS evaluation
    |
ExperimentResult
    +-- all trial states
    +-- objective values
    +-- OOS result / sanitized OOS failure state
    +-- sensitivity summary
    +-- reproducibility fingerprint
    |
ResearchRegistry
    +-- in-memory or SQLite immutable experiment metadata
```

## Search control

`ParameterSpace` only accepts explicit discrete values. It computes the Cartesian size before execution and rejects spaces over `max_combinations`.

GRID search raises if `max_trials` is smaller than the declared combination count. This prevents an apparently exhaustive experiment from silently becoming a partial search.

RANDOM search uses the experiment seed, shuffles the bounded candidate set deterministically and samples without replacement.

## Objective and constraints

Supported objective metrics are:

- total return percent,
- final equity,
- profit factor,
- maximum drawdown percent,
- win rate percent.

Each objective explicitly declares MAXIMIZE or MINIMIZE.

Independent hard constraints currently support:

- minimum trade count,
- maximum drawdown,
- minimum profit factor,
- minimum total return.

Constraints are applied to TRAIN and VALIDATION. A candidate failing TRAIN is not evaluated on VALIDATION. OOS is never used as a gate for choosing parameters.

## Reproducibility

Each experiment produces a SHA-256 fingerprint from:

- experiment id,
- strategy version,
- data version,
- base seed,
- search method,
- trial limit,
- objective,
- constraints,
- parameter-space fingerprint.

Each candidate receives a deterministic trial seed derived from the experiment seed and canonical parameter payload. Reordering execution infrastructure therefore does not change candidate seed identity.

## Error handling and sealed OOS

Expected candidate-level evaluation failures (`ValueError`, `ArithmeticError`, `IndexError`, `KeyError`) are recorded as `ERROR` trials with a sanitized error class. Unexpected infrastructure/programming failures are not swallowed.

The final OOS evaluation is attempted exactly once after parameter selection. An expected OOS failure is recorded in `ExperimentResult.oos_error` and persisted by the SQLite registry. It does not trigger fallback to the second-best parameter set or another OOS attempt, preserving the sealed-test-set contract.

This separates bad parameter candidates and OOS data failures from faults that should stop the research process.

## Sensitivity analysis

The framework aggregates completed validation objective values for every parameter/value pair and reports:

- observation count,
- mean validation objective,
- best validation objective.

This is deliberately simple and deterministic. It helps identify broad parameter stability instead of focusing only on one winning combination.

## Persistence

`InMemoryResearchRegistry` and `SQLiteResearchRegistry` provide immutable experiment identity by `experiment_id`.

Re-saving the same fingerprint is idempotent. Reusing the same experiment id with a different fingerprint raises a data-integrity error.

SQLite stores:

- experiment provenance and objective metadata,
- selected parameter payload,
- OOS objective,
- sanitized OOS error state,
- every trial's parameters, seed, status, rejection reason, train objective and validation objective.

The SQLite registry also performs an additive migration when an earlier research table exists without the `oos_error` column.

The registry stores compact research metadata rather than duplicating every historical candle or every trade payload.

## Backtest integration

`BacktestResearchEvaluator` is the explicit adapter to the existing `BacktestEngine`.

Research parameters can only alter `BacktestConfig` fields listed in an explicit `bindings` map. Unbound parameters, unknown config fields, duplicate target bindings and invalid value types are rejected. The adapter constructs a fresh validated `BacktestConfig` and never changes module-level strategy/risk constants or mutable global state.

This boundary allows future strategy-configuration objects to be introduced without letting the optimizer arbitrarily rewrite strategy code.

## Validation scope

Dedicated tests cover:

- deterministic GRID enumeration,
- GRID no-truncation behavior,
- seeded RANDOM sampling without replacement,
- Cartesian safety limits,
- TRAIN/VALIDATION selection with exactly one OOS evaluation,
- OOS failure recording without parameter reselection,
- hard-constraint rejection,
- undefined objective handling,
- candidate-level error recording,
- experiment/trial reproducibility,
- sensitivity summaries,
- in-memory registry immutability,
- SQLite registry round-trip and idempotency,
- SQLite persistence of OOS failure state,
- allow-listed and type-safe BacktestConfig parameter projection,
- invalid adapter bindings and missing dataset-role rejection.

## Final validation

The fully hardened Phase 23 branch passed the repository quality gate on GitHub Actions run `34491981084`:

- editable package installation: passed,
- compileall: passed,
- Ruff: passed,
- strict mypy: **0 issues across 143 source files**,
- pytest: **161 passed**,
- total branch-aware coverage: **75.90%**, above the required 70% floor.

The CI workflow was also corrected to validate canonical `phase-*` development branches directly, removing the stale Phase 22.5 branch-specific push trigger.

## Safety boundary

Phase 23 is a research framework. It does not submit orders, alter live execution policy, or change the existing PAPER/SHADOW execution boundary. Research results are evidence for validation, not permission to bypass strategy, risk, portfolio or execution gates.
