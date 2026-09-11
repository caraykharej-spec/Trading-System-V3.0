# Phase 36 — Repository Consolidation & CI Recovery

## Objective

Consolidate the active repository line, reconcile Phase 35 with `main`, classify legacy phase branches, restore the global CI gate, and make `main` the unambiguous release source of truth.

## Branch audit

### Phase 29 — `phase-29-execution-engine-integration`

Status: **SUPERSEDED / ARCHIVE**

- Diverged from merge base `a0b4175b85e169af37a8bea50620241281576657`.
- 18 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Contains an older execution model (`execution_models.py`, `paper_engine.py`, `storm_adapter.py`, execution journal/state helpers).
- The active line contains a newer execution architecture: atomic execution, paper runtime, pending-order management, repositories, fills, position builder, risk reservation, persistence, and validation.
- Decision: do not merge wholesale. Historical code remains available for reference only.

### Phase 30.1 — `phase-30-1-position-foundation`

Status: **SUPERSEDED / ARCHIVE**

- 7 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Older `position.py`, `position_calculator.py`, `position_events.py`, and `position_manager.py` overlap the newer `app/position/manager.py`, `settlement.py`, execution position builder, storage repositories, and runtime integration.
- Decision: do not merge wholesale.

### Phase 30.2 — `phase-30-2-portfolio-core`

Status: **SUPERSEDED / ARCHIVE**

- 12 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Historical balance/equity/portfolio state modules overlap the active `app/portfolio` account, exposure, correlation, and portfolio engine plus active analytics/storage responsibilities.
- Decision: do not merge wholesale.

### Phase 30.3 — `phase-30-3-pnl-performance-engine`

Status: **SUPERSEDED / REFERENCE**

- 25 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Contains a separate `app/performance` package with drawdown, equity curve, fees, P&L, risk metrics, and slippage helpers.
- The active architecture has consolidated performance responsibilities into `app/analytics`, `app/backtest`, portfolio/account logic, and reporting/export layers.
- Decision: no wholesale merge. Any future missing metric must be reimplemented against the active contracts rather than reviving the stale package.

### Phase 31 base — `phase-31-analytics-reporting-layer`

Status: **SUPERSEDED / REFERENCE**

- 6 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Historical analytics/dashboard modules overlap the active `app/analytics`, `app/reporting`, `app/export_system`, health dashboard facades, and API boundary.
- Decision: no wholesale merge.

### Phase 31.2 — `phase-31-2-strategy-evaluation-engine`

Status: **SUPERSEDED / REFERENCE**

- 3 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Historical strategy evaluation functionality overlaps current research/backtest/analytics responsibilities.
- Decision: keep as reference only; reimplement explicitly if a metric is proven missing.

### Phase 31.3 — `phase-31-3-risk-analytics-view`

Status: **SUPERSEDED / REFERENCE**

- 9 commits ahead of the old base line and 124 commits behind the pre-Phase-36 `main`.
- Historical risk views/alerts overlap active analytics, portfolio exposure/correlation, system health, alerting, and dashboard endpoints.
- Decision: no wholesale merge.

### Phase 31.3.4 — `phase-31-3-4-risk-dashboard-api-integration`

Status: **SUPERSEDED / REFERENCE**

- Diverged from later merge base `b10f03762790d7c113fd0d372a38395687b8a60f`.
- 3 commits ahead and 121 commits behind the pre-Phase-36 `main`.
- Historical risk dashboard API overlaps active system-health/dashboard/API components.
- Decision: no wholesale merge.

### Phase 31.4 — `phase-31-4-report-generator`

Status: **SUPERSEDED / REFERENCE**

- Diverged from merge base `b10f03762790d7c113fd0d372a38395687b8a60f`.
- 6 commits ahead and 121 commits behind the pre-Phase-36 `main`.
- Historical report builder/generator/templates overlap active reporting aggregation/specialized builders and export pipeline.
- Decision: no wholesale merge.

### Phases 32–34

Status: **INTEGRATED IN `main`**

- No dedicated `phase-32`, `phase-33`, or `phase-34` branches exist.
- System health/monitoring, deployment/runtime foundations, and production-operation validation are present in the active `main` line.

### Phase 35 — `phase-35-live-trading-operation-framework`

Status: **KEEP / RECONCILE**

- 27 commits ahead of pre-Phase-36 `main` and 0 commits behind.
- Cleanly descends from commit `212df5e22c750bc32767f639a6f85347d297b62f`.
- Adds the fail-closed live-operation framework and dedicated Phase 35 CI.
- Decision: Phase 36 is based directly on Phase 35 head `24bfbaf73c89c981bcf8f9782f6f9c29109d0a64` so the Phase 35 line is preserved without conflict or history rewriting.

## Duplicate/superseded policy

Historical duplicate packages and files are **not** copied into the active line solely because they exist on a phase branch. A legacy component can return only through a focused review that demonstrates a missing capability and adapts it to current domain contracts, persistence, risk gates, typing, tests, and observability.

This prevents parallel models such as multiple portfolio states, execution models, performance engines, or dashboard APIs from becoming competing sources of truth.

## CI recovery sequence

1. Reuse the Phase 35 Ruff fixes for deployment-runtime unused imports.
2. Run global CI on the Phase 36 line.
3. Resolve strict mypy errors in active production code; do not suppress errors globally merely to make the gate green.
4. Run the complete pytest suite with branch-aware coverage.
5. Repair functional regressions and coverage deficits if present.
6. Merge Phase 36 to `main` only after CI success.
7. Require the global CI check for future merges through branch protection/rulesets.

## Verified CI recovery result

Global CI was recovered on the Phase 36 consolidation line without weakening the strict typing gate or lowering the coverage threshold.

Verified result on GitHub Actions:

- Python compile gate: **PASS**
- Ruff lint/import-order gate: **PASS**
- Strict mypy: **PASS — 0 issues in 248 source files**
- Full pytest suite: **PASS — 285 tests**
- Branch-aware coverage: **78.24%**
- Required coverage threshold: **70%**
- CI run: **success**

The original strict-mypy failure set was reduced from 182 errors across 63 files to zero. The pytest collection collision between duplicate test basenames was fixed with pytest `importlib` import mode; no tests were deleted or excluded to obtain the green result.

## Source-of-truth decision

After Phase 36 merges:

- `main` is the canonical release line.
- Phase 29–31 branches are historical reference branches and must not be merged wholesale.
- Phase 32–35 functionality is represented by the consolidated `main` history.
- New feature work must branch from current `main`.

## Main protection gate

Phase 36 requires `main` to reject merges unless the global CI check is green. The connected GitHub integration used for this consolidation can read branch-protection/ruleset state but does not expose administration write access for protection/ruleset mutation. Therefore protection must be enabled through repository administration after the consolidated commit is green on `main`.

Required policy:

- protect `main`;
- require pull requests before merging;
- require the global `CI / quality` status check;
- require branches to be up to date before merging;
- block force pushes and branch deletion;
- do not allow bypass of required checks for normal merges.

## Safety boundary

Repository consolidation does not enable live trading. Production submission remains fail-closed and disabled until an explicitly configured venue connector and all existing production/live-operation gates pass.
