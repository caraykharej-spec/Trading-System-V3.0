# Phase 13 — Runtime Strategy Pipeline

The runtime strategy boundary converts complete multi-timeframe market snapshots into qualified, ranked opportunities. It does not place orders.

## Flow

```text
Universe
  ↓
Snapshot Loader
  ↓
1D + 4H + 1H + 15M Market Snapshots
  ↓
Strategy Engine
  ↓
R:R + Score + Confidence
  ↓
READY_FOR_RISK_REVIEW
  ↓
Sort by Score → Confidence → R:R
  ↓
Top 10
  ↓
Risk / Portfolio Gate
```

The pipeline does not bypass position monitoring, recovery, or persistence. Risk and portfolio approval remain downstream hard gates.

## Ranking contract

At most 10 qualified opportunities are returned. If fewer than 10 qualify, only the qualified set is returned. There is no open-position count limit in this stage.

## Safety boundary

This phase does not execute live broker/exchange orders. It is suitable for paper/shadow orchestration and later API integration.
