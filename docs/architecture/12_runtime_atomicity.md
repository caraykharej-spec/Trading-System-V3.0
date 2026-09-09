# Phase 12.2 — Atomic Execution, Fill, Position, and Account Persistence

## Objective

Prevent a crash between execution and persistence from leaving an inconsistent state such as a recorded fill without an active position.

## Transaction boundary

For a confirmed fill, the local SQLite transaction is:

```text
OrderResult(FILLED)
    ↓
orders.status = FILLED
    ↓
Fill Ledger INSERT
    ↓
Position INSERT/UPDATE
    ↓
COMMIT
```

If any write fails, the transaction is rolled back.

SQLite repositories expose `auto_commit=False` for this transaction boundary. Normal standalone repository operations retain `auto_commit=True` for compatibility.

## Idempotency

Order IDs and fill IDs are unique persistence keys. A repeated identical result/fill is accepted as the same persisted fact; conflicting data is rejected.

## Account state

`account_state` stores the current persisted equity for the default account. It is intentionally separated from the in-memory account object so runtime restart can reconstruct equity from durable state.

## Recovery rule

On restart, the system must reconcile these durable facts before creating or mutating a position:

1. Load order state.
2. Load fills for filled orders.
3. Load open positions.
4. Detect a filled order with a missing position.
5. Rebuild the position from the authoritative `OrderRequest + OrderResult` and fill record.
6. Persist the repaired position in a transaction.

The reconciliation step is the next hardening target; this phase establishes the durable facts and atomic write boundary needed by it.

## Safety

LIVE execution remains disabled. This phase only strengthens persistence for PAPER/SHADOW development workflows.
