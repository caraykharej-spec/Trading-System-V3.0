# Phase 38.1 — Statistical Threshold Calibration

## Objective

Phase 38.1 replaces purely hand-selected strategy-validation thresholds with an auditable statistical calibration layer while preserving the fail-closed safety guarantees introduced in Phase 38.

Calibration does not create trading signals, change risk sizing, submit orders, or activate live execution. It only derives a `StrategyValidationPolicy` that can be consumed by the existing `StrategyQualificationEngine`.

## Design principles

1. **Independent calibration cohort** — the candidate currently being evaluated must not calibrate its own acceptance thresholds.
2. **Temporal isolation** — an optional timezone-aware cutoff excludes observations at or after the evaluation boundary.
3. **Deterministic statistics** — empirical thresholds use deterministic linear-interpolated quantiles over Decimal values.
4. **Never loosen Phase 38** — empirical calibration may tighten the baseline policy but can never make a threshold easier than the supplied Phase 38 guardrail.
5. **Fail closed** — insufficient cohort size, insufficient metric coverage, missing policy evidence, or duplicate sample IDs produces `HOLD` or an explicit error.
6. **Auditable output** — each calibrated metric records its empirical threshold, baseline guardrail, applied threshold, direction, and sample count.
7. **Reproducible dataset identity** — the eligible calibration cohort receives a deterministic SHA-256 fingerprint independent of input ordering.

## Implemented module

### `app/strategy_validation/calibration.py`

The module introduces:

- `CalibrationObservation` — one independent historical validation snapshot;
- `ThresholdCalibrationConfig` — minimum cohort sizes and quantile configuration;
- `CalibratedThreshold` — per-metric empirical/baseline/applied audit record;
- `ThresholdCalibrationReport` — `CALIBRATED` or `HOLD`, cohort counts, fingerprint, reasons, and optional policy;
- `ThresholdCalibrator` — deterministic calibration engine;
- `CalibrationStatus` and `ThresholdDirection` enums.

`CalibrationObservation.from_evidence(...)` converts existing Phase 38 validation evidence into a calibration snapshot without creating a parallel validation stack.

## Calibrated metrics

The following continuous Phase 38 thresholds are calibrated:

### Higher-is-better metrics

- minimum OOS return;
- minimum OOS profit factor;
- minimum profitable walk-forward ratio;
- minimum Monte Carlo median return;
- minimum feasible research-trial ratio;
- minimum forward hit rate;
- minimum forward mean return.

The empirical candidate is the configured lower quantile. The applied threshold is:

```text
max(existing Phase 38 minimum, empirical lower quantile)
```

Therefore calibration can tighten a minimum but cannot reduce it.

### Lower-is-better metrics

- maximum OOS drawdown;
- maximum Monte Carlo worst drawdown;
- maximum cost-stress degradation;
- maximum normalized parameter spread.

The empirical candidate is the configured upper quantile. The applied threshold is:

```text
min(existing Phase 38 maximum, empirical upper quantile)
```

Therefore calibration can tighten a maximum but cannot increase it.

## Thresholds intentionally not calibrated

Phase 38.1 does not statistically relax structural sample-count requirements such as:

- minimum OOS trade count;
- minimum walk-forward window count;
- minimum regime trade count;
- minimum number of qualified regimes;
- minimum forward observation count.

Those values remain explicit baseline guardrails because lowering them from a small historical cohort would weaken evidence quality rather than improve calibration.

## Default statistical configuration

```text
minimum calibration observations: 20
minimum observations per calibrated metric: 20
lower quantile: 0.25
upper quantile: 0.75
```

Projects may intentionally tighten these values, but a downstream caller may not bypass a `HOLD` report or substitute missing metrics with defaults.

## Leakage controls

The calibration cohort is a separate input from candidate qualification evidence.

An optional `cutoff` may be supplied to `ThresholdCalibrator.calibrate(...)`. Only observations satisfying:

```text
observation.as_of < cutoff
```

are eligible. This prevents future evidence or same-boundary observations from entering historical threshold estimation.

Duplicate `sample_id` values are rejected because repeated observations could otherwise overweight one historical period or experiment.

## Dataset fingerprint

Eligible observations are sorted deterministically by sample ID and timestamp and serialized into a canonical representation. A SHA-256 fingerprint identifies the exact calibration cohort used for the report.

The fingerprint is stable across input ordering, allowing calibration results to be tied to a reproducible evidence set in research, review, or release records.

## Qualification integration

`StrategyQualificationEngine.from_calibration(report)` creates the existing Phase 38 qualification engine only when the report contains an approved calibrated policy.

```text
Independent Historical Validation Evidence
                ↓
        CalibrationObservation[]
                ↓
         ThresholdCalibrator
                ↓
       CALIBRATED / HOLD
          ↓            ↓
 calibrated policy    stop
          ↓
StrategyQualificationEngine
          ↓
   QUALIFIED / HOLD
```

The calibration layer does not override any qualification check. It only supplies a policy whose continuous thresholds are at least as strict as the Phase 38 baseline.

## Failure semantics

The report is `HOLD` and exposes no usable policy when:

- total eligible cohort size is below `minimum_samples`;
- any required metric has fewer observations than `minimum_metric_samples`;
- a time cutoff removes too much evidence;
- required evidence categories are absent from too many historical samples.

Duplicate sample IDs and invalid metric ranges raise explicit validation errors rather than being silently ignored.

## Safety boundary

Phase 38.1 is a research/release calibration layer only.

It does **not**:

- change strategy score or confidence calculations;
- change trade-risk or portfolio-risk policy;
- approve a strategy with missing Phase 38 evidence;
- enable order submission;
- modify Phase 35 live-operation gates;
- activate a venue connector;
- guarantee future profitability.

A calibrated `QUALIFIED` strategy must still pass all independent strategy, context, risk, portfolio, execution, production-readiness, and live-operation gates.

## Validation

Core implementation validation on the Phase 38.1 feature branch:

- Python compile gate: PASS;
- Ruff lint/import-order gate: PASS;
- strict mypy: PASS — 0 issues in 295 source files;
- pytest: PASS — 354 tests;
- branch-aware coverage: 79.57%;
- required coverage threshold: 70%.

Additional final CI is required after documentation/integration commits, followed by pull-request CI and merged-`main` verification before Phase 38.1 is closed.
