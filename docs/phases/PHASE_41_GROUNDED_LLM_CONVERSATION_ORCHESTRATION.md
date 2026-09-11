# Phase 41 — Grounded LLM Conversation & Assistant Orchestration

## Status

IMPLEMENTED AND CI-VALIDATED on the Phase 41 implementation line.

Verified global quality results:

- Python compile: PASS
- Ruff: PASS
- strict mypy: PASS — 0 issues in 283 source files
- full pytest: PASS — 319 tests
- branch-aware coverage: 79.61% (required threshold: 70%)

The final branch head and merged `main` commit must also pass the same global workflow before the phase is closed.

## Goal

Phase 41 introduces a conversation/orchestration boundary above the deterministic Phase 40 copilot. Its purpose is to let an API, dashboard, Android client, or optional model-backed narrator answer natural-language questions using only recorded trading-system evidence.

The phase does not give an LLM authority to calculate signals, approve risk, size positions, change portfolio gates, activate live trading, or submit orders.

## Architecture

```text
User Query
    ↓
AssistantIntentRouter
    ↓
Fresh CopilotMarketBrief
    ↓
GroundingBuilder
    ↓
EvidenceCitation[]
    ↓
AssistantOrchestrator
    ├────────────→ Deterministic Response
    │
    └────────────→ GroundedLanguageModel (optional)
                           ↓
                      ModelReply
                           ↓
              Citation / Safety Validation
                    ↓              ↓
                 ACCEPT          REJECT
                    ↓              ↓
              Model Answer    Safe Deterministic Fallback
```

## Added package

```text
app/assistant/
├── __init__.py
├── models.py
├── model.py
├── router.py
├── grounding.py
├── session.py
└── orchestrator.py
```

## Intent routing

`AssistantIntentRouter` currently supports:

- `MARKET_BRIEF`
- `SYMBOL_EXPLANATION`
- `REJECTION_REASON`
- `RISK_SUMMARY`
- `HELP`
- `UNKNOWN`

The router is deterministic. It selects which recorded evidence should be exposed to the conversation layer; it does not make trading decisions.

A bounded session may provide the previous symbol for a natural follow-up such as `What about its risk?`, but conversation state never supplies market/risk facts itself.

## Grounding contract

`GroundingBuilder` converts `CopilotMarketBrief` / `CopilotItemBrief` data into `EvidenceCitation` objects.

Each citation contains:

```text
citation_id
key
value
source
symbol (optional)
```

Examples:

```text
BTCUSD:strategy:score
BTCUSD:risk:risk_percent
BTCUSD:portfolio:correlated_risk_percent
ETHUSD:gate_reason:1
MARKET:copilot:evaluated
```

Citation IDs are generated only from recorded copilot facts, ranks, statuses, gate reasons, or market-level counters. Missing facts are not inferred.

## Grounded model contract

Phase 41 defines the provider-neutral `GroundedLanguageModel` protocol:

```text
ModelPrompt -> ModelReply
```

`ModelPrompt` includes only:

- normalized user query,
- routed intent,
- fixed system instructions,
- bounded evidence citations,
- bounded recent user-query history,
- optional routed symbol.

It does not include an execution client, exchange connector, risk mutation callback, or live-operation gateway.

`ModelReply` contains:

- text,
- citation IDs used by the answer.

No external model provider SDK is hard-coded by this phase. Without a configured implementation of `GroundedLanguageModel`, the assistant remains deterministic and operational.

## Fail-closed model validation

A model answer is accepted only if all of the following are true:

1. response text is non-empty,
2. at least one citation is supplied when evidence exists,
3. every citation ID exists in the current grounding bundle,
4. duplicate citation IDs are rejected,
5. every returned citation appears visibly in response text as `[citation_id]`,
6. the response does not contain blocked execution-oriented imperatives.

The current execution-oriented rejection set includes phrases such as:

```text
buy now
sell now
place an order
execute an order
execute the trade
open a position
increase leverage
set leverage
go long
go short
```

If provider invocation raises an exception or the reply violates the contract, the orchestrator returns deterministic grounded output and records an unknown marker such as:

```text
model_error
model_output_rejected
```

This means model availability or model quality cannot make the assistant fail open.

## UNKNOWN behavior

Unsupported questions or missing evidence remain explicit.

Examples:

```text
UNKNOWN: the question cannot be answered from the current grounded copilot contract.
UNKNOWN: no grounded copilot evidence is available for that symbol.
UNKNOWN: no grounded risk facts are available for ...
```

The assistant does not fabricate a price target, probability, signal, provider state, news state, or risk value when the corresponding evidence is unavailable.

## Session boundary

`InMemoryConversationStore` is deliberately bounded.

Default limits:

```text
max_turns = 6
max_sessions = 100
```

Session IDs are limited to letters, numbers, `_`, and `-`, with a maximum length of 64 characters.

Stored session data is limited to:

- recent user query,
- routed intent,
- routed symbol.

The store does not retain model-generated responses as authoritative state and does not cache trading evidence. `AssistantOrchestrator` reloads the current `CopilotMarketBrief` on every request.

## API boundary

Phase 40 routes remain available:

```text
GET /assistant/brief
GET /assistant/opportunity?symbol=BTCUSD
```

Phase 41 adds:

```text
POST /assistant/query
```

Example JSON body:

```json
{
  "query": "Why was ETHUSD rejected?",
  "session_id": "mobile_1"
}
```

The stdlib HTTP adapter limits assistant JSON request bodies to 16 KiB. `TradingApiService` limits normalized assistant queries to 2000 characters.

## Assistant response contract

`AssistantResponse` contains:

```text
intent
text
citations
mode
symbol
grounded
unknowns
model_used
execution_authority
```

`execution_authority` is always `False`.

Answer modes:

- `DETERMINISTIC`
- `MODEL`
- `UNKNOWN`

## Safety boundary

The assistant path is intentionally parallel to execution:

```text
DecisionEvidence + Gate Trace
    ↓
Copilot
    ↓
Assistant / Optional LLM
    ↓
Explanation only
```

The execution path remains:

```text
Strategy
    ↓
Context
    ↓
Strategy Qualification
    ↓
Core Risk
    ↓
Portfolio Gate
    ↓
Production Readiness
    ↓
Live Risk / Circuit Breaker
    ↓
Execution Gateway
```

Phase 41 does not modify `app/execution` or `app/live_operation` and does not add a connector from `app/assistant` to either domain.

## Test coverage added

Phase 41 tests verify:

- deterministic grounded answer without a model,
- acceptance of a valid model reply with visible allowed citations,
- rejection of invented citation IDs,
- rejection of execution-oriented model output,
- preservation of upstream gate-rejection reasons,
- `UNKNOWN` behavior for unsupported/unavailable information,
- bounded session follow-up context,
- invalid session-ID rejection,
- API serialization with `execution_authority = False`.

## Remaining provider work

Phase 41 deliberately stops at a provider-neutral model contract. A concrete external LLM adapter, credentials/secrets lifecycle, provider retries/timeouts, usage/cost controls, and provider-specific telemetry require separate implementation and validation.

Any future adapter must preserve this invariant:

```text
LLM provider != trading authority
```

and must not receive direct execution capabilities.
