# Phase 16 — Paper Trading Runtime

## Objective

Complete the runtime lifecycle for PAPER mode from a selected `OrderRequest` through fill/pending state and persisted `Position` creation. Live execution remains disabled.

## Runtime cycle

```text
START
  -> Recovery
  -> Load OPEN positions
  -> Live price / SL / TP management
  -> Persist exits + realized P&L
  -> Check durable pending LIMIT orders
  -> Persist fill atomically
  -> Create Position atomically
  -> Strategy/Risk/Portfolio evaluation
  -> User-selected OrderRequest(s)
  -> PAPER execution
       -> FILLED: Fill + Position atomically
       -> ACCEPTED LIMIT: durable pending order
       -> REJECTED: terminal order state
  -> Audit COMPLETED
```

## Guarantees

- PAPER mode never submits to a broker/exchange.
- Existing positions are checked against live price before new order evaluation.
- A confirmed fill creates a position only through `AtomicExecutionService`.
- Order result, fill and position are committed as one transaction when using the same database connection.
- Accepted LIMIT orders survive process restart through `SQLitePendingOrderRepository`.
- Re-running the same order ID with an identical request is idempotent.
- Reusing an order ID with different request data is rejected.
- Completed runtime cycles are idempotent by cycle ID.
- User selection remains explicit; the runtime does not automatically trade every Top-N candidate.
- No real-money/live execution is implemented.

## Persistence

Phase 16 adds the `pending_orders` SQLite table with a foreign key to `orders`. Pending orders are removed only after their fill has been persisted successfully.

## Scope boundary

Phase 16 does not implement broker connectivity, live execution, mobile UI, or production deployment. It provides a deterministic paper runtime suitable for subsequent reliability and data-quality hardening.
