# Phase 11 — Backtesting & Historical Simulation

## Purpose

The backtest layer evaluates the existing strategy/risk philosophy on historical OHLCV data without calling a broker or exchange.

## Execution model

1. Historical candles are supplied for `1d`, `4h`, `1h`, and `15m`.
2. At each completed 15m candle, only candles whose own close time is already known are used for analysis.
3. Strategy evaluation occurs after the 15m close.
4. A valid signal is filled at the **next 15m candle open**. This prevents using the signal candle's future open.
5. Existing positions are checked against the current candle's OHLC.
6. Stop Loss has priority when both SL and Take Profit are touched inside the same candle. This is a conservative intrabar assumption.
7. Slippage and commissions are configurable and default to zero for deterministic baseline tests.
8. Positions still open at the end of the dataset are closed at the final available 15m close and marked `END_OF_TEST`.

## Risk model

The baseline simulator uses:

- 1% risk per trade.
- 4% maximum aggregate open risk.
- 50% maximum simulated position capital.
- No fixed maximum number of open positions.
- Position amount is sized from stop distance and the configured risk budget.

These are simulation constraints, not a live-execution authorization.

## Metrics

`BacktestResult` reports:

- initial/final equity
- total return
- win rate
- profit factor
- maximum drawdown
- trade records
- rejected signals
- maximum concurrent positions
- open positions remaining at the end

## Important limitations

This phase is a deterministic simulation foundation, not a claim of institutional-grade backtest accuracy. It does not yet model exchange-specific fills, bid/ask spread, funding, partial fills, liquidation, contract-specific fees, market-impact models, or a full event/news calendar. Those should be added before using results for serious strategy validation.

Historical data must be clean, correctly timestamped, sufficiently complete for all four timeframes, and free from survivorship/look-ahead bias.
