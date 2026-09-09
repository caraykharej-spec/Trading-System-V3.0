# Phase 15 — Runtime Decision & Order Preparation

## Objective

Convert a fully qualified opportunity into a validated `OrderRequest` without submitting or executing it.

## Pipeline

```text
Universe
  -> Market Data
  -> Strategy
  -> READY_FOR_RISK_REVIEW
  -> Risk Gate
  -> Portfolio Gate
  -> Qualified Top-N
  -> User Selection
  -> Order Preparation
  -> OrderRequest
  -> Phase 16 Paper Runtime
```

## Rules

- Only `GatedOpportunity` objects that passed Strategy, Risk, and Portfolio gates may be prepared.
- Default preparation type is `LIMIT` because the strategy supplies an explicit entry level.
- `LIMIT` uses the strategy entry as `requested_price`.
- `MARKET` leaves `requested_price` unset; the executor obtains the fill price later.
- Stop Loss and Take Profit are copied from the strategy signal and remain attached to the order request.
- Quantity and approved leverage come from `RiskAssessment`; order preparation must not resize or reinterpret risk.
- Order preparation performs validation but never submits an order.
- Order IDs are deterministic for the same symbol/side/entry/SL/target combination to support idempotent preparation.
- There is no live execution in Phase 15.

## Risk boundary

The risk engine now exposes the selected leverage in `RiskAssessment`. This prevents the preparation layer from guessing leverage from unrelated portfolio metrics.

## Safety boundary

Phase 15 does not change account equity, open positions, realized P&L, or risk budgets. Those mutations belong to the execution/fill lifecycle.

## Exit safety remains unchanged

Every runtime cycle continues to monitor existing positions against live price and process Stop Loss before continuing with new opportunity evaluation.

## Deliverables

- `app/application/order_preparation.py`
- `tests/unit/test_order_preparation.py`
- leverage propagation in `app/risk/risk_engine.py`

## Not included

- broker/exchange submission
- live trading
- automatic user selection
- automatic order placement for every Top-N candidate
- mobile UI
