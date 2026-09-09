# Phase 14 — Strategy → Risk → Portfolio Gate

## Objective

Phase 14 makes Risk and Portfolio hard gates in the runtime opportunity-selection path. The system must not present an opportunity as a final Top-10 candidate until it passes both gates.

## Flow

```text
Universe
  ↓
Market snapshots
  ↓
Strategy
  ↓
READY_FOR_RISK_REVIEW
  ↓
Risk Engine
  ├─ 1% max risk / trade
  ├─ 4% max aggregate open risk
  ├─ Storm max 10% SL loss / position amount
  ├─ 50% max futures capital
  └─ 2% max correlated risk
  ↓
Portfolio Engine
  ├─ aggregate risk
  ├─ correlated risk
  └─ futures capital
  ↓
Qualified Opportunities
  ↓
Sort by score → confidence → R:R
  ↓
Top 10
```

There is no fixed maximum number of open positions. Portfolio capacity is determined by risk, correlation, futures-capital, and related constraints.

## Implementation

`app/application/strategy_pipeline.py` now exposes `evaluate_all()`. This is important because applying Top-10 before risk approval can hide lower-ranked opportunities that should be considered after a higher-ranked candidate is rejected.

`app/application/opportunity_pipeline.py` introduces:

- `RiskContext`: account, open positions, instrument, contract, leverage, provider, and candidate correlation.
- `GatedOpportunity`: strategy signal plus its Risk and Portfolio assessments.
- `OpportunityPipeline`: Strategy → Risk → Portfolio → final ranking.
- `OpportunityPipelineResult`: evaluation counts and final qualified candidates.

The pipeline never submits orders.

## Policy invariants

The default limits are synchronized from `RiskPolicy` into `PortfolioPolicy`:

- maximum risk per trade: 1%
- maximum aggregate open risk: 4%
- maximum correlated risk: 2%
- maximum futures capital: 50%
- Storm maximum SL loss relative to position amount: 10%

Storm's SL-loss rule remains provider-specific and is evaluated by the Risk Engine.

## Ranking rule

Ranking is performed **after** all hard gates:

1. score descending
2. confidence descending
3. R:R descending

The final list contains at most 10 candidates. If fewer than 10 pass all gates, fewer are returned. A user can choose any candidate in the final Top-10 set.

## Safety boundary

Phase 14 does not enable live execution. The output is an approved opportunity/risk assessment and remains downstream of the paper/shadow execution architecture.
