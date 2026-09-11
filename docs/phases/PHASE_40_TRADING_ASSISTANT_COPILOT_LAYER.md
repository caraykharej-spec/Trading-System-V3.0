# Phase 40 — Trading Assistant / Copilot Layer

## Status

IMPLEMENTED AND CI-VALIDATED on the Phase 40 feature branch.

## Objective

Phase 40 adds a read-only, evidence-grounded assistant layer above the existing deterministic trading pipeline. Its purpose is to explain what the system already knows: ranked opportunities, strategy evidence, context state, gate outcomes, risk, portfolio state, and rejection reasons.

The copilot does not calculate trading signals, override gates, size positions, submit orders, activate live execution, or invent missing values.

## Architecture

```text
Market / Strategy / Context / Risk / Portfolio
                    ↓
            DecisionEvidence
                    ↓
             Gate Trace
                    ↓
            CopilotExplainer
                    ↓
       Structured Copilot Brief
                    ↓
      API / Android / Future LLM UI
```

The assistant consumes deterministic domain outputs. Any future model-backed natural-language layer must consume the structured copilot contract rather than raw exchange/execution interfaces.

## Added domain

`app/copilot` contains:

- `models.py` — read-only brief/fact/status contracts.
- `explainer.py` — deterministic evidence renderer for qualified and rejected candidates.
- `__init__.py` — public copilot exports.

### Copilot statuses

- `QUALIFIED`
- `HOLD`
- `REJECTED`
- `NO_TRADE`
- `UNAVAILABLE`

All copilot response objects set `execution_authority = False`.

## Gate trace

Before Phase 40, the application pipeline retained aggregate rejection counts but discarded symbol-level rejection detail. Phase 40 adds backward-compatible gate trace records without changing decision semantics.

Recorded stages:

- `STRATEGY`
- `CONTEXT`
- `RISK`
- `PORTFOLIO`

Recorded outcomes:

- `NO_TRADE`
- `HOLD`
- `REJECTED`

Examples of preserved upstream reasons include:

- no aligned HTF direction,
- no approved setup,
- context event-window hold,
- aggregate open-risk budget exhausted,
- leverage above contract maximum,
- correlated-risk limit exceeded,
- futures-capital limit exceeded.

The copilot copies these reasons from upstream deterministic objects. It does not rewrite a failed gate into a successful recommendation.

## Qualified-opportunity explanation

For qualified opportunities, the copilot reads immutable `DecisionEvidence` when available and exposes source-labelled facts such as:

- direction,
- setup,
- score,
- confidence,
- planned R:R,
- market regime,
- HTF trend,
- structure state,
- news/event context,
- candidate risk percent,
- aggregate risk,
- correlated risk,
- futures capital percent,
- provider.

If `DecisionEvidence` is unavailable, the explainer reports that limitation and only uses fields present on the qualified signal/risk/portfolio objects.

## API boundary

Phase 40 adds read-only callbacks and GET routes:

```text
GET /assistant/brief
GET /assistant/opportunity?symbol=BTCUSD
```

The API service remains a thin adapter. Business logic and explanation semantics stay in `app/copilot` and upstream domains.

No assistant POST route can submit an order. The existing `/runtime/cycle` endpoint is unchanged and remains separate from copilot output.

## Future model / LLM boundary

Phase 40 intentionally does not add an external LLM dependency. A future model-backed interface may transform a structured copilot brief into richer natural language, but must obey these rules:

1. use structured facts and reasons as the source of truth;
2. mark missing evidence as unavailable rather than infer it;
3. never create prices, scores, probabilities, risk limits, or provider state that are absent from source evidence;
4. never call execution APIs directly;
5. never convert `HOLD`, `REJECTED`, or `NO_TRADE` into a trade instruction;
6. remain downstream of context, strategy qualification, risk, portfolio, readiness, and live-operation gates.

## Validation

The first complete Phase 40 implementation run passed the global `CI / quality` workflow:

- compileall: PASS
- Ruff: PASS
- strict mypy: PASS — 0 issues in 276 source files
- pytest: PASS — 310 tests
- branch-aware coverage: 79.51%
- required coverage threshold: 70%

The final documentation head and merged `main` commit must pass the same workflow before the phase is considered closed.

## Safety boundary

```text
Copilot output
    ↓
Explanation only
    ↓
NO execution authority
```

The copilot cannot bypass:

```text
Context Policy
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

Live execution remains disabled by default.