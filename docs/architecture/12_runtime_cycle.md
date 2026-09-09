# Phase 12 Runtime Cycle

The implemented runtime boundary is restart-aware and persists cycle state.

## Current cycle

```text
START
  ↓
Load persisted open positions
  ↓
Live-price SL/TP/trailing-stop management
  ↓
Persist changed positions
  ↓
Apply realized P&L to account
  ↓
Reconcile persisted pending limit orders (when configured)
  ↓
Persist COMPLETED audit
```

If an exception occurs, the cycle is persisted as `FAILED` and the exception is re-raised.

## Recovery invariant

A cycle may be retried with the same `cycle_id`. If the persisted audit is already `COMPLETED`, the result is returned without running the cycle again. If the cycle was `STARTED` and the process crashed, the cycle can resume from persisted state.

Closed positions are excluded by the position repository on the next run, so an already-persisted stop/take-profit cannot be applied a second time by the position-management stage.

## Persistence

SQLite now contains a `cycle_audits` table alongside the existing position table. The dedicated `SQLiteCycleAuditRepository` also creates the table defensively when initialized.

## Deliberate boundary

This phase does **not** yet create positions from pending fills because `OrderResult` currently does not carry the authoritative `OrderRequest` metadata required for SL/TP and leverage reconstruction. The next execution-persistence step should add a persistent order repository and make the fill-to-position bridge consume that stored request.

Market scanning, strategy, risk, portfolio approval, and new-order execution remain later runtime stages. Live broker/exchange execution is not enabled.
