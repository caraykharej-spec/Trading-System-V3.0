# Phase 46 — Full System Qualification & Failure Injection

## Objective

Exercise critical cross-layer safety invariants under controlled offline faults
and produce a machine-readable qualification artifact. “Full system” means the
repository's critical data, atomicity, live-safety, evidence, recovery and
configuration boundaries. It does not mean destructive chaos against a real
venue, production account, network, database or host.

## Qualification matrix

| Case | Injected condition | Required invariant |
|---|---|---|
| DATA-PRIMARY-OUTAGE | Primary price provider raises | Valid fallback is used once |
| DATA-TOTAL-OUTAGE | Every provider raises | No price is manufactured |
| DATA-STALE | Provider returns stale price | Freshness gate rejects it |
| EXEC-PERSISTENCE-ROLLBACK | Fill persistence raises | Rollback; no commit or position write |
| LIVE-DISABLED | Explicit live enable is false | Connector receives zero submissions |
| LIVE-CIRCUIT-OPEN | Emergency circuit is open | Connector receives zero submissions |
| EVIDENCE-TAMPER | Stored report is modified | Hash-chain verification fails |
| EVIDENCE-RESTORE | SQLite online backup is restored | Record count and chain remain valid |
| CONFIG-MISSING-SECRET | Production API key is absent | Configuration fails closed |

All cases are critical and use the production classes, bounded fakes and
in-memory SQLite. Fake connectors count calls but never perform network I/O.
No scenario contains credentials or an execution-capable venue adapter.

## Evidence contract

`trading-system-qualification --output <path>` writes JSON containing:

- per-case category, expected and observed behavior;
- exercised controls, status and duration;
- sanitized exception class when a scenario itself fails;
- total/failed/critical-failed counts;
- SHA-256 digest over canonical case results;
- explicit `live_execution_attempted=false`.

Any failed case makes the process exit nonzero. Exception messages are excluded
to prevent secrets or injected content from entering artifacts. Duration is
diagnostic only and is not a performance benchmark.

## CI and governance

The `Full System Qualification` workflow runs on the Phase 46 branch, every PR
to `main`, merged `main`, and manual dispatch. It installs the same package,
runs the matrix, re-runs dedicated tests, and retains the report artifact for
30 days. The existing global Python quality and container security workflows
remain mandatory independent gates.

## Interpretation and limitations

A PASS proves that these deterministic injections satisfied their asserted
invariants for the tested revision. It does not prove venue availability,
profitability, every possible failure combination, process-kill recovery,
filesystem corruption tolerance, regional disaster recovery, production TLS,
alert delivery or a seven-day Phase 45 soak.

No deliberate fault is sent to Storm, Gate.io, Yahoo, OpenAI or a live account.
Provider/network chaos and host-level drills require an isolated staging
environment with explicit authorization, bounded blast radius and rollback.

## Closure gates

Repository implementation is complete only when:

1. all nine critical cases pass on feature and PR heads;
2. global Python CI passes;
3. container build and HIGH/CRITICAL scan pass;
4. the qualification JSON artifact is retained;
5. merge is followed by the same three successful workflows on `main`.

Operational system qualification remains HOLD until Phase 44 deployment evidence
and Phase 45 soak/backup/restore evidence exist. This phase cannot enable live
execution or override any prior HOLD.
