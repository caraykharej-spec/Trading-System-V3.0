# Phase 22 — Trade Journal and Performance Analytics

## Purpose

Create an immutable completed-position journal and a read-only analytics layer so paper/shadow runtime outcomes can be audited and evaluated without mixing reporting logic into strategy, risk, execution, or HTTP adapters.

## Journal model

Every completed position is normalized into a `JournalEntry` containing factual execution state: position id, symbol, side, entry/exit prices, stop, optional target, amount, quantity, leverage, realized P&L, open/close timestamps, close reason, and optional runtime cycle id.

`position_id` is the journal idempotency key. Re-saving an identical entry is a no-op. Reusing the same position id with different facts is treated as a data-integrity conflict rather than silently overwriting history.

The journal is available through in-memory and SQLite repositories. SQLite adds indexed `trade_journal` persistence by close time and symbol.

## Restart recovery

`RuntimeCycleOrchestrator` reconciles already-closed positions against the journal before monitoring new open positions. This repairs a journal row that may have been missed by an interrupted prior cycle. Newly closed positions are journaled after realized equity persistence.

Reconciliation never guesses P&L, prices, timestamps, or close reasons. It only journals complete closed-position facts already present in authoritative position persistence.

## Analytics

`AnalyticsService` derives a `PerformanceReport` from journal facts. Current metrics are:

- total trades, wins, losses, and breakeven trades
- gross profit and gross loss
- net realized P&L
- win rate
- average P&L, average win, and average loss
- profit factor
- expectancy
- maximum consecutive losses
- best and worst realized trade

Analytics may be filtered by symbol. Metrics are deterministic and read-only; they never alter trading decisions or position state.

## API integration

The thin API can expose a configured analytics callback at:

`GET /analytics/performance`

When no analytics provider is configured, the service returns an explicit `ANALYTICS_UNAVAILABLE` conflict rather than fabricating empty production data.

The packaging configuration now includes both `app*` and `interfaces*`, ensuring the Phase 21 HTTP/API package is present in installed deployments instead of existing only on the source-tree Python path.

## Safety and limitations

This phase is for paper/shadow evaluation. Performance statistics describe recorded historical simulation/runtime outcomes only and are not predictions or guarantees of future results.

The journal stores the stop value present on the completed `Position`. A later phase can add richer lifecycle/event journaling for original stop, trailing-stop history, setup metadata, score/confidence, fees, and context snapshots without mutating these immutable completed-position facts.
