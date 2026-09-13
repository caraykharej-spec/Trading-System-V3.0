# Phase 47.3 — Persistent Candle Cache & Incremental Market Scan

## Objective

Reduce repeated OHLCV transfer and bound full-universe scan latency without
weakening freshness, source qualification, strategy, risk, or execution gates.

## Architecture

`IncrementalCandleService` reuses the Phase 37 `CandleHistoryStore`. A cold
series requests the configured history window and persists canonical candles.
A warm series requests only the mutable two-candle tail, performs idempotent
timestamp upserts, reloads the bounded window, and fails closed when fewer than
the required candles exist.

`StormDrivenUniverseResolver.get_candles_with_provenance` records the configured
route and the provider that actually returned valid candles after fallback.
The original `get_candles` API remains compatible.

`BudgetedMarketScanner` adds a total scan budget, structured progress events,
bounded concurrency, deterministic ranking, and end-of-pass retry of transient
provider failures. Permanent strategy rejection is never retried.

## Evidence contract

The full-universe runner reports:

- cache database path and cycle budget;
- budget-exceeded state and retried markets;
- per-symbol/per-timeframe cache and download counts;
- configured and actual providers after fallback;
- progress events for start, completion, failure, retry and budget exhaustion;
- explicit target-symbol decisions;
- a separate `degen_markets` report whose entries remain `RESEARCH_ONLY`.

## Target symbols

AMD, COIN, CRCL and SPX already have explicit registry routes and must be
qualified through the incremental scan. SUI may use an automatically
price-qualified exact Gate.io route when discovered; it must not be added to the
persistent registry without captured live qualification evidence. SPCX is not a
known registry key. The runner reports SPCX and SPXC separately so a typo cannot
silently map to SPX or another instrument.

## Safety

The phase is read-only/PAPER-only. Cache state and progress cannot authorize an
order, bypass market-data validation, convert missing data to NO_TRADE, or
enable live execution.

## Closure gates

1. Cold load persists the complete bounded candle window.
2. Warm load requests only the mutable tail and produces identical analysis.
3. Fallback provenance names the actual provider.
4. Duplicate candle timestamps remain idempotent across restart.
5. Total budget exhaustion is explicit and fail-closed.
6. Only retryable data failures enter the bounded retry pass.
7. AMD, COIN, CRCL, SPX, SPCX/SPXC and SUI receive explicit decisions.
8. Degen markets are reported separately as RESEARCH_ONLY.
9. CI, strict mypy, Ruff, coverage, qualification and container security pass.
10. Cold/warm benchmark evidence demonstrates at least 90% fewer downloaded
    candles and at least 60% lower warm-cycle duration without coverage loss.
