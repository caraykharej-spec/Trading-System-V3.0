# Phase 47 — Storm Trade Cost, Funding & TON Fee Integration

## Outcome

Phase 47 establishes a read-only, fail-closed cost contract for Storm Trade and TON. It does
not enable order submission or wallet signing.

## Venue evidence

`StormCostService` reads each public `/markets` record and snapshots the market address,
protocol fee, execution fee, rollover fee, funding interval and directional rates, VPI spread,
price-impact limits, price-spread limit, and liquidation fee ratio. Original raw values are
retained beside normalized values for auditability.

Missing venue values remain `UNKNOWN`. A required unknown fee raises `ProviderError`; it is
never silently converted to zero.

## Calculation semantics

- Protocol fees use current position notional. Entry and exit are calculated separately.
- Funding accrues using the venue funding period and directional market rate.
- A positive cost is paid by the account; a negative cost is received by the account.
- VPI spread is optional evidence and may be excluded on close under Storm's documented
  no-closing-spread policy.
- TON fee evidence progresses from estimate/reservation to transaction-hash-backed settlement.
  The settled on-chain value is authoritative.

## Historical-backtest boundary

Historical backtests must consume time-aligned snapshots. Current `/markets` values must not be
applied retrospectively to old candles. Until historical Storm fee/funding snapshots have been
accumulated, research must use explicitly labelled scenarios and qualification stress ranges.

## Sources

- Storm Fees: <https://docs.storm.tg/costs-and-practice/fees>
- Storm PnL and ROI: <https://docs.storm.tg/managing-a-position/pl_and_roi>
- Storm Oracles: <https://docs.storm.tg/how-the-protocol-works/price_feeds>
- TON fee estimation: <https://docs.ton.org/api/v2/send/estimate-fee>
