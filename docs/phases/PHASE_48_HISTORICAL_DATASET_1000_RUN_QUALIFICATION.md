# Phase 48.1 — Dataset Versioning & Qualification Foundation

Status: IMPLEMENTATION IN REVIEW\n\nPhase 48 is split into independently reviewed increments: 48.1 dataset versioning and statistical contracts; 48.2 locked OOS and walk-forward; 48.3 reproducible 1,000-run matrix; 48.4 shuffling/bootstrap/Monte Carlo; 48.5 synthetic paths/noise/data robustness; 48.6 parameter sensitivity/stability; 48.7 regime/time robustness; 48.8 execution-cost and market-impact stress; 48.9 final statistical report and qualification.

## Objective

Produce reproducible, leakage-safe and statistically defensible strategy
qualification evidence. A successful process exit or a count of 1,000 completed
runs is never sufficient for qualification.

## Locked policy

The initial policy is fixed before observing Phase 48 results:

- at least 1,000 uniquely identified runs;
- at least 200 OOS or walk-forward runs;
- at least 1,000 aggregated OOS trades;
- OOS profit factor at least 1.10;
- lower bound of the 95% confidence interval for OOS expectancy above zero;
- OOS 95th-percentile maximum drawdown no greater than 25%;
- median IS-to-OOS expectancy degradation no greater than 35%;
- zero unresolved duplicate timestamps, illegal gaps or unregistered splits.

Changing these gates requires a new policy version and cannot retroactively
qualify an existing experiment.

## Dataset contract

Every dataset version records its provider, provider symbol, retrieval time,
source URI, license identifier, symbol, timeframe, coverage range, candle count,
split policy and SHA-256 content fingerprint. Dataset content is immutable:
changed candles produce a new hash and version.

Quality checks fail closed on:

- duplicate or non-chronological timestamps;
- unexpected candle spacing, unless session gaps are explicitly allowed;
- invalid OHLCV values;
- mixed symbols or timeframes;
- split events without an explicit adjustment declaration;
- missing provenance.

## Qualification matrix

The 1,000-run matrix will combine:

- chronological IS, validation, locked OOS and walk-forward windows;
- symbols, timeframes and market regimes;
- fee, spread, slippage and funding stress;
- trade-order permutation and bootstrap Monte Carlo;
- delayed or missed execution and parameter perturbation.

Each run must retain a unique ID, dataset version, split, seed, strategy/config
fingerprints and cost assumptions.

## Decisions

The batch gate returns one of:

- `QUALIFIED`
- `QUALIFIED_WITH_LIMITS`
- `INSUFFICIENT_SAMPLE`
- `OVERFIT_SUSPECTED`
- `FAILED_STATISTICAL_QUALIFICATION`

The vertical slice implements the versioned dataset manifest and statistical
batch gate. Subsequent Phase 48 increments will connect the existing backtest,
walk-forward, Monte Carlo and cost-stress engines to the durable evidence
runner, then execute and publish the real 1,000-run matrix.

## Safety

All Phase 48 outputs are research evidence. Qualification cannot enable live
execution, bypass risk gates or imply future profitability.
