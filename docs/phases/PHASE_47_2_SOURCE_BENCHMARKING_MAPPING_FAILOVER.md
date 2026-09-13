# Phase 47.2 — Source Benchmarking, Mapping Registry & Adaptive Failover

## Outcome

The signal engine no longer rediscovers the preferred OHLC source on every run. A versioned
registry stores the qualified route order for each non-standard Storm asset while Storm remains
the authoritative active `base/USDT` universe and reference price.

## Source policy

- Crypto uses Gate Spot/Futures first when the contract is semantically equivalent.
- Equities use Yahoo OHLCV first and Gate TradFi OHLC as a no-key fallback.
- Forex uses two no-key routes: Yahoo currency charts and Gate TradFi/CFD.
- Metals and oil use Yahoo futures OHLCV first and Gate TradFi/CFD for validation/failover.
- Tokenized-stock spot wrappers are not qualified primary sources.

The registry explicitly stores provider symbol, price multiplier, volume requirement, latency
budget, minimum history, and maximum allowed deviation from Storm. `1000PEPE`, `TON/GRAM`, and
the current `NFLX ×10` normalization are provider-bound mappings rather than hidden strategy
logic. TON uses the mature Gate Spot `GRAM_USDT` history first; the newer perpetual and Yahoo
routes remain fallbacks because their daily histories do not yet satisfy the 220-candle gate.

## Adaptive failover

For every request, the selected route must pass its latency budget, minimum candle count and
volume policy. A failed route falls through in registry order. Three consecutive failures open
an in-memory five-minute circuit breaker. If no route qualifies, the asset fails closed and is
reported; invalid or stale data never enters the strategy pipeline.

## Benchmarking

`scripts/market_data/benchmark_sources.py` performs a read-only benchmark over every configured
route and reports:

- live-price deviation from Storm;
- request latency;
- candle counts for `1d`, `4h`, `1h`, and `15m`;
- volume availability;
- qualification result and reason.

The benchmark never rewrites the production mapping automatically. Registry promotion remains
an explicit reviewed code change so a transient provider slowdown cannot silently alter signal
semantics.

## Safety boundary

This phase adds public market-data reads only. It does not authorize Storm orders, wallet
signatures, automatic position entry, or live execution. The operating mode remains
`PAPER_READ_ONLY`.
