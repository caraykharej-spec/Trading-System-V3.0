# Phase 19 — Context Engine

The context layer provides deterministic external-risk context without adding arbitrary score bonuses.

## Domain

- News: `SUPPORTIVE`, `NEUTRAL`, `ADVERSE`, `UNKNOWN`.
- Economic events: `NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- Events support country, actual, forecast, previous, optional symbol relevance, and calculated surprise.
- Event windows distinguish pre-event and post-event risk windows.

## Gating policy

- CRITICAL events can block new trading.
- HIGH events can delay a new decision without being a hard block.
- ADVERSE news is context, not an automatic score penalty or trade block.
- Missing/stale news is `UNKNOWN`, never treated as supportive.
- Context never overrides data-quality, strategy, risk, or portfolio hard gates.

## Safety

The engine is analytical and paper/shadow compatible. It does not submit live orders and does not manufacture missing calendar/news data.
