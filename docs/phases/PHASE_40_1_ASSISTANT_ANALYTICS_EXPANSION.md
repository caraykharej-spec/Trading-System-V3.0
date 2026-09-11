# Phase 40.1 — Assistant Analytics Expansion

## Status

Implementation target: grounded, read-only assistant analytics for positions, journal history, market change and bounded what-if scenarios.

This phase extends the existing Phase 40/41/42 assistant stack. It does not create a parallel analytics or conversation system and it does not grant the assistant execution authority.

## Objective

The assistant previously grounded answers primarily in Copilot opportunity/gate evidence. Phase 40.1 adds four additional evidence domains:

1. open-position analytics;
2. authoritative trade-journal analytics;
3. current market change relative to completed-candle references;
4. explicit percentage what-if simulation.

All outputs are source-labelled through `EvidenceCitation` before deterministic narration or optional language-model narration.

## Architecture

```text
Position Repository ───────┐
Journal Repository ────────┤
Live Price Provider ───────┼──→ AssistantAnalyticsService
Market Data Platform ──────┘              ↓
                                  grounded snapshots
                                           ↓
User Query → AssistantIntentRouter → GroundingBuilder
                                           ↓
                                  EvidenceCitation[]
                                           ↓
                                  AssistantOrchestrator
                                  ├─ deterministic answer
                                  └─ optional grounded LLM
```

`AssistantAnalyticsService` is read-only. It receives providers for existing authoritative state and returns immutable analytics snapshots.

## Position analytics

`AssistantIntent.POSITIONS` exposes grounded facts from the open-position repository plus current live-price evidence.

Per-position evidence can include:

- position ID and symbol;
- side;
- entry price;
- current price;
- stop loss and take profit;
- recorded amount and quantity;
- leverage;
- opened-at timestamp;
- read-only unrealized P&L.

Unrealized P&L reuses the existing `calculate_realized_pnl(...)` contract so assistant math does not introduce a competing P&L model.

If a required live price cannot be obtained, the corresponding P&L is not invented. The missing source is reported explicitly.

## Journal analytics

`AssistantIntent.JOURNAL` reads immutable completed-position records from the existing journal repository and reuses `analyze_performance(...)`.

Grounded metrics include:

- total trades;
- wins, losses and breakeven trades;
- net P&L;
- win rate;
- average P&L;
- expectancy;
- profit factor when available;
- average realized R multiple when available;
- maximum consecutive losses;
- recent completed trades with realized P&L, return, close reason and close timestamp.

The journal remains the authority for completed-trade history. Assistant narration cannot rewrite journal records.

## Market-change analytics

`AssistantIntent.MARKET_CHANGE` requires an explicit symbol.

For each configured timeframe (`15m`, `1h`, `4h`, `1d`), the comparison is:

```text
reference = prior completed candle close
current   = current live price
change %  = (current - reference) / reference × 100
```

The prior completed candle is used deliberately rather than the latest potentially forming candle. Each timeframe preserves its reference timestamp, reference close and computed percentage as cited evidence.

Unavailable candle series are reported as missing evidence; they are not silently replaced with fabricated values.

## What-if analytics

`AssistantIntent.WHAT_IF` is a bounded read-only simulation, not a forecast and not a trading recommendation.

The current contract requires:

- an explicit symbol; and
- an explicit percentage move such as `+5%`, `-5%`, `rises 5%` or `falls 5%`.

For a scenario percentage `p`:

```text
hypothetical_price = current_price × (1 + p / 100)
```

For matching open positions, the service calculates:

- current unrealized P&L;
- hypothetical P&L at the simulated price;
- per-position P&L delta;
- aggregate P&L delta.

The accepted percentage range is greater than `-100%` and at most `+1000%`. A scenario that would imply a non-positive price is rejected.

What-if evaluation does not mutate:

- position state;
- stop loss;
- take profit;
- leverage;
- risk budgets;
- pending orders;
- execution state;
- venue state.

Every what-if response remains `execution_authority = false`.

## Intent routing

The deterministic router now recognizes English and Persian terms for:

- positions;
- journal/history;
- market change;
- what-if scenarios.

Unsigned percentages can infer direction from bounded directional language such as `falls 5%` or `rises 5%`.

Missing symbol or scenario percentage fails closed to `UNKNOWN`/missing evidence rather than inventing an assumption.

## Lazy Copilot evaluation

Phase 40.1 separates symbol discovery from Copilot evaluation when the composition root supplies the configured universe.

Analytics intents therefore do not trigger a full opportunity scan merely to answer a position, journal, market-change or what-if question.

Copilot evaluation is still loaded for Copilot-owned intents:

- market brief;
- symbol opportunity explanation;
- rejection reason;
- risk summary.

This preserves the current decision architecture while avoiding unnecessary market scans for analytics-only queries.

## Grounding and model boundary

The optional language model receives only the citations produced by `GroundingBuilder`.

Phase 40.1 extends the grounding policy:

- no invented position state;
- no invented journal results;
- no invented market-change values;
- no invented what-if inputs or outputs;
- what-if results must not be described as predictions;
- no recommendation to open/close a position;
- no instruction to change stop, leverage or position size;
- no order submission or live activation.

Invalid model citations or execution-oriented responses continue to fail closed to deterministic output.

## Composition integration

The PAPER composition root now builds one `AssistantAnalyticsService` from existing providers:

```text
positions_provider  → SQLitePositionRepository.list_open
journal_provider    → SQLiteJournalRepository.list_all
live_price_provider → existing routed live-price function
candles_provider    → ProductionMarketDataPlatform.get_candles
```

The assistant receives the configured universe through `symbols_provider`, enabling lazy Copilot evaluation for analytics intents.

The API remains the existing read-only assistant query boundary. No assistant mutation endpoint is introduced.

Application API version advances from `3.0.0-dev5` to `3.0.0-dev6`.

## Safety boundary

Phase 40.1 does not modify strategy scoring, qualification, risk acceptance, portfolio gating, PAPER order authorization or the Phase 35 live-operation boundary.

No `app/execution` or `app/live_operation` behavior is expanded by this phase.

Assistant analytics are explanatory calculations over existing state. They cannot authorize or execute a trade.

## Verification

Core feature-head CI after the strict-typing repair:

- compileall: PASS;
- Ruff: PASS;
- strict mypy: PASS — 0 issues in 296 source files;
- pytest: PASS — 362 tests;
- branch-aware coverage: 79.81%;
- required coverage: 70%.

The final documentation head, pull-request head and merged `main` commit must also pass `CI / quality` before Phase 40.1 is closed.
