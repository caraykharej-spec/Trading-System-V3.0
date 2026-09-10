# Phase 18 — Advanced Market Structure

## Purpose

Replace the minimal rolling support/resistance interpretation with a deterministic swing-based market-structure layer.

## Components

- `SwingPoint`: confirmed pivot high/low with timestamp, price, and source index.
- `StructureBreak`: explicit directional break classified as BOS or CHOCH.
- `AdvancedStructureResult`: swing history, structural trend, current structure, latest break, structural support/resistance, and bounded score.

## Rules

1. Candles are ordered chronologically.
2. Duplicate timestamps are rejected.
3. A swing requires a configurable pivot window on both sides.
4. Bullish structure requires both a higher high and higher low.
5. Bearish structure requires both a lower high and lower low.
6. Mixed sequences are `TRANSITION`, never forced into a directional trend.
7. A close beyond the latest confirmed swing is classified as a break.
8. A break aligned with the established structural trend is `BOS`; a break against it is `CHOCH`.
9. Insufficient history returns `UNKNOWN` rather than inventing structure.

## Safety

The engine is analytical only. It does not place orders and does not override data-quality, strategy, risk, or portfolio gates.
