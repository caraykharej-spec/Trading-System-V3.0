# Phase 48.3 — Real 1000-Run Matrix & Reproducibility

Status: REAL EXECUTOR READY FOR SMOKE

Phase 48.3 consumes one exact, successful Phase 48.2 full-summary artifact. It
does not read a mutable `latest` result and it does not select assets from their
observed OOS performance. The sealed Phase 48.2 evidence fingerprint controls
the complete matrix plan.

## Matrix contract

The matrix is the exact Cartesian product of:

- one Phase 48.2 dataset-bundle fingerprint;
- `LOCKED_OOS` and `WALK_FORWARD` evidence splits;
- 500 deterministic seed labels;
- one frozen strategy fingerprint;
- one fingerprint of the per-asset locked configuration policy; and
- the Phase 48.2 locked Storm baseline-cost scenario.

This produces exactly 1,000 unique experiment identities. The 79 executable
assets are assigned deterministically and as evenly as possible across those
identities. `SKY` and `SPCX` remain evidence-only and performance-excluded until
real warm-up history exists.

Seeds in this phase are reproducibility labels and select a sealed pre-OOS
walk-forward window. They do not pretend to create independent market samples.
Trade shuffling, bootstrap and Monte Carlo begin in Phase 48.4.

## Real execution

Every matrix experiment invokes `BacktestEngine` over HF-backed candles whose
partition, qualification, dataset, strategy and configuration fingerprints are
rechecked against Phase 48.2. Locked OOS uses the original sealed OOS boundary.
Walk-forward uses only the pre-OOS windows recorded by Phase 48.2.

The 1,000 experiments are distributed over ten asset-stable shards. Each shard
downloads an asset once and reuses its verified in-memory candles for that
asset's assigned experiments. This keeps provider traffic bounded without
changing experiment identity or evidence.

## Checkpoint and resume

Each experiment writes a JSONL attempt record immediately after execution.
Successful experiments are skipped when an earlier Phase 48.3 run is supplied
as `resume_run_id`. Failed attempts remain in the evidence and may be retried by
a later workflow run; aggregation selects the latest attempt while retaining
the total attempt count.

Missing experiments, conflicting checkpoints, a changed Phase 48.2 fingerprint,
an invalid plan, dataset drift, strategy drift or configuration drift fail
closed.

## Workflow sequence

1. Run `Phase 48.3 Real 1000-Run Matrix` with `scope=smoke` and the exact Phase
   48.2 full-summary run ID and artifact name.
2. Verify all 10 real-engine smoke experiments and the aggregate artifact.
3. Run the same workflow with `scope=full`.
4. If a full run has infrastructure failures, start a new workflow with the
   failed run ID in `resume_run_id`; do not use `Re-run all jobs` as a substitute
   for checkpoint-aware resume.

The successful aggregate status is `PASS_1000_RUN_EXECUTION_EVIDENCE`. It proves
real-engine execution and reproducibility, not strategy profitability or live
trading eligibility. Statistical qualification remains Phase 48.9.
