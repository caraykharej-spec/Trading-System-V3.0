# Phase 02 — Domain and Data Foundation

## Objective

Establish normalized domain contracts before connecting external providers or implementing the strategy.

## Domain objects

- `Instrument`: canonical symbol, asset class, tradability and quantity constraints.
- `LivePrice`: normalized live price with provider and timestamp.
- `Candle`: normalized OHLCV record with timeframe and timestamp.
- `Position`: entry, stop, total amount, quantity, leverage, lifecycle and realized P&L.
- `Account`: starting equity plus realized P&L and aggregate open-risk calculation.

## Provider boundary

External providers implement `MarketDataProvider`. The rest of the application must not depend on Storm/Gate.io/Yahoo SDKs or response formats.

V3 providers are currently limited to Storm, Gate.io and Yahoo Finance. Pyth is excluded.

## Live-price rule

A live price used for position monitoring must carry its provider and timestamp. A stale response must be rejected by the data layer rather than silently treated as live.

## Position accounting

At the beginning of every application cycle:

1. Load open positions from persistence.
2. Fetch a valid live price for each position.
3. Evaluate the side-aware stop condition.
4. Mark crossed positions stopped out.
5. Calculate realized P&L against the configured total position amount and provider contract rules.
6. Apply realized P&L to account equity.
7. Recalculate aggregate open risk from the remaining open positions.

The generic domain must not assume that every provider has identical leverage/P&L mechanics. Storm-specific behavior belongs in its adapter/contract implementation.

## Decimal policy

Prices, amounts, quantities, leverage and P&L use `Decimal` in the domain to avoid binary floating-point accounting errors.

## PyCharm and Android

The domain and application services remain UI-independent. PyCharm runs the local Python entry point. A future HTTP/API adapter can expose the same application services to Android without moving business rules into the mobile client.
