# Phase 47.1 — Signal Engine Output Readiness

## Outcome

This increment closes the prerequisites for the first user-visible signal-engine run without
granting live execution authority.

## Account

The existing PAPER composition, API runtime, backtest, Monte Carlo and analytics contracts use
`10,000 USDT` as the validated default initial equity. `TRADING_INITIAL_EQUITY` remains the
explicit runtime override. Persisted current equity is never reset on restart.

## Structural stop loss

The strategy uses the latest confirmed 4H swing low for LONG and swing high for SHORT. A
`0.25 × ATR(14)` buffer is placed beyond that structural level. The signal exposes both
`stop_loss_source` and `stop_loss_buffer`; downstream Storm, risk, R:R and sizing gates remain
mandatory.

## All evaluated markets

`OpportunityPipelineResult.all_evaluations` contains every requested symbol, including
`QUALIFIED`, `HOLD`, `REJECTED`, and `NO_TRADE`. Qualified candidates keep their complete rank
even outside the Top 10. Available score components, news/event context, Entry, SL, TP, R:R,
confidence and rejection reasons are exposed through:

`GET /api/v1/markets/evaluations`

The Dashboard Markets view renders this full collection separately from Ranking.

## Asset journal statistics

Every runtime cycle writes one idempotent evaluation row per symbol. Asset analytics combine
that history with authoritative positions and completed Journal entries to expose evaluation
count, Top-10 count/rate, average/best score, positions opened, and complete per-symbol P&L
performance through:

`GET /api/v1/analytics/assets`

Cycle replay cannot double-count history because `(cycle_id, symbol)` is the primary key.
