# Phase 12 — Runtime Integration, Persistence, and Recovery

## Objective

Connect the already-built domain components at the application boundary without moving business rules into the UI or execution adapter.

## Scope

1. Persist the complete position lifecycle, including take-profit.
2. Treat a confirmed execution fill as the only source for creating an active position.
3. Preserve the collateral/notional/leverage relationship used by the position model.
4. Keep the mandatory position-monitoring phase first in every cycle.
5. Make restart recovery depend on persistent positions rather than in-memory state.
6. Add regression tests around persistence and fill-to-position conversion.

## Fill-to-position contract

```text
OrderRequest
    |
    v
ExecutionEngine
    |
    v
FILLED OrderResult
    |
    v
position_from_fill()
    |
    v
PositionRepository.save()
```

A rejected, cancelled, pending, or otherwise non-filled order must never create an active position.

For leveraged positions:

```text
notional = fill_price * quantity
collateral = notional / leverage
```

`Position.total_amount` represents the collateral/position amount used by the current risk and Storm-specific loss model; it must not silently become gross notional.

## Persistence contract

SQLite persistence must round-trip:

- identity
- symbol and side
- entry price
- stop loss
- take profit
- quantity
- leverage
- collateral/position amount
- lifecycle status
- timestamps
- exit price
- realized P&L
- close reason

Existing databases are migrated by `database.connect()` when the take-profit column is missing.

## Recovery contract

On restart, the application loads active positions from the repository before scanning for new opportunities. The first safety action remains live-price/SL monitoring.

The application must not reconstruct open positions from signals, UI state, or transient execution objects.

## Phase boundary

Phase 12 does **not** enable live broker/exchange execution. Paper/shadow remain the execution boundary. API/Android integration is a later interface concern.

## Remaining work

- Persist and reconcile pending limit orders.
- Persist cycle/audit events.
- Add explicit shadow-mode semantics.
- Add idempotent recovery for execution and position transitions.
- Integrate market/strategy/risk/portfolio flow into the application runner.
- Add API boundary after the core runtime contract is stable.
