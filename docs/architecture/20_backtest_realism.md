# Phase 20 — Backtest Realism and Validation Hardening

## Purpose

Strengthen historical simulation so reported paper-research results explicitly account for execution frictions instead of assuming fills at the raw OHLC price.

## Scope

- Full bid/ask spread model with half-spread applied on entry and exit.
- Directional slippage remains separate from spread.
- Commission remains percentage-based and deterministic.
- Signed daily funding model for leveraged-style instruments.
- Funding is accrued on each simulated 15-minute holding interval and recorded on the completed trade.
- Existing intrabar safety rule is preserved: when both stop and target are touched in one candle, stop loss wins.
- All realism parameters are optional and default to zero, preserving backward-compatible deterministic behavior.

## Cost semantics

`spread_percent` is the full quoted spread. A long entry pays half the spread and a long exit receives the bid; shorts are mirrored.

`slippage_percent` is an adverse execution adjustment applied independently from spread.

`funding_rate_percent_per_day` is a signed daily rate on position notional. A positive rate is a cost for longs and a credit for shorts; a negative rate reverses that relationship. This is a generic research model, not an exchange-specific funding contract.

## Safety and limitations

This phase does not claim exchange-level fill accuracy. It does not infer historical order books, liquidation waterfalls, maker/taker schedules, partial fills, market impact, borrow fees, dividends, corporate actions, or instrument-specific funding conventions. Those require provider/instrument-specific historical datasets.

The backtest remains a research and paper-validation component. It must not be interpreted as a guarantee of future performance or live execution behavior.
