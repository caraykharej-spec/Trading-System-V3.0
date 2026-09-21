# Phase 48.6 — Parameter Sensitivity & Stability

Status: REAL EXECUTOR READY FOR SMOKE

This phase reruns the real strategy over the locked Phase 48.2 out-of-sample and
walk-forward ledgers carried through the completed Phase 48.3 and Phase 48.5
evidence. The executor verifies the complete `48.5 -> 48.3 -> 48.2` chain before
sealing a plan. It does not synthesize performance from the earlier summaries.

The sealed plan contains one baseline plus four deterministic one-at-a-time
perturbations for each live strategy acceptance parameter:

| Parameter | Frozen baseline | Evaluated values |
| --- | ---: | --- |
| `min_rr` | 2.5 | 2.0, 2.25, 2.75, 3.0 |
| `min_score` | 90 | 80, 85, 95, 100 |
| `min_confidence` | 90 | 80, 85, 95, 100 |

This produces 13 unique scenarios. Data fingerprints, evaluation boundaries,
backtest configuration, execution costs, and all non-varied strategy parameters
remain frozen. The sweep is diagnostic only and must not be used to select a
better parameter value during the qualification sequence.

The workflow accepts exact successful full Phase 48.5 and Phase 48.3 artifact
coordinates. `smoke` runs all 13 scenarios on one locked ledger for up to eight
distinct assets (up to 104 evaluations). `full` runs all scenarios over every
unique locked ledger (2,522 evaluations when the source contains the observed
194 ledgers). Both scopes are distributed over ten reproducible ledger shards.

Each parameter is evaluated against four fail-closed stability gates: finite
outputs, maximum permitted degradation, minimum stable-neighborhood fraction,
and maximum adjacent performance cliff. Bound clipping is deterministic and
colliding clipped scenarios are deduplicated before evaluation. Total scenario
cardinality is capped to prevent accidental combinatorial or runtime expansion.

The report uses a canonical parameter ordering and SHA-256 identities for the
plan, every evaluation, the ordered result set, and the final report. Execution
completion and statistical stability are separate fields: a complete workflow
receives an execution-evidence status while `stability_passed` records the
four-gate stability verdict. This prevents a technically complete run from
being misreported as a robust strategy.

The recommended progression is smoke first, inspect its artifact, and only then
launch full. Phase 48.6 remains research/PAPER only and cannot override weak
return evidence from earlier phases.
