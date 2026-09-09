# Phase 12 Runtime Cycle

The runtime boundary is restart-aware and now integrates persisted execution recovery.

## Current cycle

```text
START
  ↓
Recovery reconciliation
  ↓
Load persisted open positions
  ↓
Live-price SL/TP/trailing-stop management
  ↓
Persist changed positions
  ↓
Apply realized P&L to account
  ↓
Reconcile pending limit orders
  ↓
Persist pending fills atomically: Order → Fill → Position
  ↓
Remove pending order only after durable fill persistence
  ↓
Persist COMPLETED audit
```

If an exception occurs, the cycle is persisted as `FAILED` and the exception is re-raised.

## Restart invariants

- A completed `cycle_id` is replayed without executing the cycle again.
- A previously `STARTED` cycle can resume from durable state.
- Recovery repairs a missing position only when a persisted `FILLED` order has exactly one fill record.
- Multiple fills are reported as an explicit reconciliation issue; recovery does not guess how to aggregate them.
- Pending limit fills are persisted before their pending record is removed. If the process crashes after persistence but before removal, the next cycle can safely repeat the fill check because the order/fill/position persistence is idempotent.
- Recovery never mutates account equity merely because a position was reconstructed; realized P&L must come from the exit lifecycle.

## Persistence

SQLite contains durable order, fill, position, account-state, and cycle-audit records. Atomic execution requires the participating SQLite repositories to share the same connection with transaction commits disabled at the repository level.

## Deliberate boundary

Market scanning, strategy, risk, portfolio approval, and new-order execution remain later runtime stages. Live broker/exchange execution is not enabled.
