# Live Operation Runbook

## Purpose

Operational procedure for controlled production activation of Trading-System-V3.0.

## Pre-activation requirements

- Phase 34 Go-Live Readiness report approved.
- Production environment selected explicitly.
- Core RiskPipeline healthy and producing executable approvals only.
- LiveRiskController limits configured for the production account.
- System health snapshot is healthy.
- Exchange production connector reports connected, authenticated, and trading-enabled.
- Position reconciliation has no unresolved mismatch.
- No unresolved CRITICAL incident exists.
- Secrets are supplied by the runtime environment or secret manager, never repository files.

## Activation sequence

1. Start production runtime in execution-disabled state.
2. Start data providers, scanner, strategy, risk, portfolio, analytics, and health services.
3. Validate market-data freshness and oracle/exchange connectivity.
4. Reconcile local positions against the venue.
5. Verify production risk limits and account state.
6. Generate a Phase 34 readiness result.
7. Construct a LiveActivationRequest with explicit_live_enable=False and verify it remains blocked.
8. Enable live execution only through an explicit runtime action after all prior checks pass.
9. Submit production orders only through LiveExecutionGateway.
10. Monitor execution latency, connector health, position synchronization, and incidents continuously.

## Immediate halt conditions

Live order submission must be blocked when any of the following is true:

- Health readiness becomes false.
- Exchange connector loses authentication or trading readiness.
- Core or live risk approval fails.
- A critical incident is open.
- Position synchronization reports unresolved mismatch.
- Duplicate order identity is detected.
- Production environment is not explicitly selected.

## Incident response

1. Open an incident with component, severity, and diagnostic message.
2. For CRITICAL incidents, stop new order submission immediately.
3. Preserve existing state and logs before corrective action.
4. Reconcile venue and local position/account state.
5. Acknowledge the incident only after ownership is assigned.
6. Resolve only after health, reconciliation, and readiness gates pass again.
7. Require a fresh activation evaluation before resuming production submission.

## Recovery

- Never assume local state is authoritative after connectivity failure.
- Compare venue positions with local positions first.
- Restore persistent state from the latest validated source when required.
- Re-run Phase 32 health validation and Phase 34 readiness gates before resuming.

## Rollback

If production activation is unsafe, return to SHADOW or PAPER operation. Live execution must remain disabled while strategy, analytics, dashboard, and data-health components may continue operating for diagnosis.

## Audit evidence

Retain activation decisions, risk decisions, execution results, reconciliation reports, incidents, health snapshots, and deployment identifiers as the minimum live-operation audit trail.
