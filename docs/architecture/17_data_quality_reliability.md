# Phase 17 — Data Quality & Reliability Hardening

## Objective

Market data is a hard prerequisite for strategy, risk, portfolio, and paper-trading decisions. Phase 17 makes unreliable data fail closed instead of silently reaching the decision layer.

## Quality gates

### Live prices
- positive, finite price
- non-empty symbol/provider
- timezone-aware timestamp
- future timestamp rejected beyond tolerance
- configurable maximum age

### OHLCV
- supported timeframe
- expected timeframe consistency
- timezone-aware timestamps
- finite OHLCV values
- high >= low
- open/close inside high-low range
- non-negative volume
- strict chronological order
- exact timeframe spacing; gaps and duplicates are rejected
- optional latest-series freshness check
- optional incomplete-last-candle rejection

### Anomaly checks
- configurable close-to-close return threshold
- configurable candle-range threshold
- volume anomaly warning when history is insufficient or the latest volume is extreme

## Provider reconciliation

`reconcile_live_prices()` validates all candidate prices first, then compares valid providers against a deterministic reference. Excessive disagreement invalidates the result.

`reconcile_candles()` validates each provider independently and compares overlapping close prices. A large disagreement invalidates the series; missing overlap is a warning rather than an invented match.

The system never averages conflicting provider prices to manufacture a synthetic value.

## Reliability controls

`call_with_retry()` provides bounded exponential backoff.

`CircuitBreaker` tracks consecutive provider failures and temporarily blocks a failing provider. A successful request resets the failure state.

`ProviderRouter` now:
1. selects providers in configured order;
2. checks provider circuit state;
3. retries transient failures;
4. validates the returned payload;
5. falls back to the next provider when validation fails;
6. fails closed when no provider returns reliable data.

Both live-price and candle routing use these controls.

## Safety boundary

A fallback provider is acceptable only when its data passes the same quality checks. Provider failure, stale data, malformed OHLCV, gaps, or excessive cross-provider disagreement must not be converted into a strategy signal.

Phase 17 does not enable live execution. Paper/shadow workflows remain the validation boundary.
