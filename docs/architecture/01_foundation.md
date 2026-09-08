# Phase 01 — Architecture Foundation

## 1. System boundary

The V3 system is a Python domain application. It must run directly from PyCharm without a GUI or web server dependency. Interfaces are adapters around the core, not owners of business logic.

```text
PyCharm / Scheduler / Future API
              |
              v
      Application Runner
              |
      +-------+--------+
      |                |
      v                v
Position Monitor   Market/Strategy Flow
      |                |
      v                v
Portfolio/Risk <--- Qualified Opportunities
      |
      v
 Paper/Shadow Execution
```

A future Android application communicates with an API boundary. Android does not contain the authoritative strategy or risk rules.

## 2. System-cycle contract

Every run follows this order:

1. Load runtime state.
2. Load active positions.
3. Obtain the latest valid live price for each active position.
4. Compare live price with the position stop loss.
5. If the stop is crossed, close/mark the position as stopped out and calculate realized P&L.
6. Recalculate equity and aggregate open risk.
7. Validate data freshness/quality.
8. Evaluate market regime and higher-timeframe context.
9. Detect approved setups.
10. Validate 15-minute entry confirmation.
11. Build score and confidence.
12. Apply R:R and risk/portfolio gates.
13. Rank qualified opportunities and expose up to Top 10.
14. Do not execute a trade automatically in foundation mode.
15. Persist an auditable cycle result.

The position-monitoring phase is mandatory even when no new market opportunity is being generated.

## 3. Stop-loss semantics

For a long position:

```text
live_price <= stop_loss -> stop triggered
```

For a short position:

```text
live_price >= stop_loss -> stop triggered
```

The monitor must use a provider-aware price source and must never silently use stale market data as a valid live-price confirmation.

### P&L

V3 separates:

- entry price
- exit price
- total position amount/notional
- leverage
- margin/collateral
- quantity
- provider-specific loss mechanics
- realized P&L
- account equity

For Storm, the observed platform behavior indicates that stop-loss loss relative to the position amount is affected by leverage. This is therefore a Storm-specific contract rule and must not be hard-coded as a universal market formula.

## 4. Hard gates vs score

```text
Gates = Can this opportunity be traded?
Score = Which already-valid opportunity is better?
```

A failed hard gate is not compensated by a high score.

Core gates include data quality, regime eligibility, HTF alignment, structure, approved setup, 15m confirmation, liquidity/volume, valid SL, R:R >= 2.5, confidence policy, risk limits, and portfolio constraints.

## 5. Strategy hierarchy

| Timeframe | Responsibility |
|---|---|
| 1D | Macro trend/context |
| 4H | Primary trend and market structure |
| 1H | Setup detection |
| 15M | Entry confirmation |

Primary V1 setups:

- BREAKOUT_RETEST
- TREND_PULLBACK
- CONTINUATION

## 6. Risk policy

- MAX_RISK_PER_TRADE = 1.0% equity
- MAX_AGGREGATE_OPEN_RISK = 4.0% equity
- MAX_STORM_SL_LOSS_PCT_OF_POSITION_AMOUNT = 10%
- MIN_RISK_REWARD = 2.5
- No fixed maximum number of open positions

Portfolio controls may additionally restrict correlation, exposure, margin, leverage, concentration, and available capital.

## 7. Scoring

The target evidence-based score is:

| Component | Weight |
|---|---:|
| HTF Trend Alignment | 20 |
| Market Structure | 15 |
| Setup Quality | 25 |
| Entry Confirmation | 15 |
| Volume/Liquidity | 10 |
| Volatility Quality | 5 |
| Risk/Reward Quality | 10 |
| **Total** | **100** |

Score and confidence remain independent dimensions.

## 8. Data-source boundary

V3 does not include Pyth. Data providers are isolated behind provider interfaces. Normalization, freshness, quality, and reconciliation belong to the data layer.

## 9. Persistence and recovery

The application must be restart-safe. Active positions, state transitions, cycle identifiers, realized P&L, and audit records belong in persistent storage. In-memory state is only a runtime cache.

## 10. Safety of execution

Foundation mode uses paper/shadow execution. A future live adapter must require an explicit configuration capability and must remain outside the strategy engine.
