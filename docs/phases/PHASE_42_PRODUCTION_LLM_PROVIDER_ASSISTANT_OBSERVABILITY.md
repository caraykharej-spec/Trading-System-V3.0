# Phase 42 — Production LLM Provider Integration & Assistant Observability

## Status

IMPLEMENTED AND CI-VALIDATED on the Phase 42 implementation branch.

Core implementation validation:

- Python compile gate: PASS
- Ruff lint/import-order gate: PASS
- strict mypy: PASS — 0 issues in 288 source files
- full pytest suite: PASS — 329 tests
- branch-aware coverage: 79.42% (required threshold: 70%)

The final documentation head and merged `main` commit must also pass the same global workflow before the phase is closed.

## Objectives

Phase 42 turns the provider-neutral Phase 41 language-model contract into an optional production integration boundary while preserving deterministic trading authority and the fail-closed assistant design.

The phase has two explicit responsibilities:

1. Production LLM provider/runtime/observability integration.
2. Explicit application market-data source ownership:
   - Storm for live price,
   - Gate.io for primary OHLCV,
   - Yahoo Finance for OHLCV fallback.

Phase 42 does not enable live trading and does not add any model-to-execution path.

## Market-data source policy

The application composition root now creates role-specific routers through `MarketDataSourcePolicy` and `build_market_data_routers`.

Default policy:

```text
live_price_providers = ("storm",)
ohlcv_providers      = ("gateio", "yahoo")
```

Resulting read paths:

```text
Live price request
    ↓
Storm
    ↓
ProviderRouter retry / circuit breaker
    ↓
Freshness + live-price quality validation
    ↓
Runtime / risk / PAPER execution consumers
```

```text
OHLCV request
    ↓
Gate.io
    ↓ provider failure / unsupported symbol / invalid data
Yahoo Finance
    ↓
ProviderRouter retry / circuit breaker
    ↓
Freshness + OHLC integrity + outlier validation
    ↓
Market analysis / strategy
```

The policy fails closed when a required configured provider is absent. Provider names inside a role must be unique.

### Storm boundary

Storm remains the application live-price source. The existing Storm adapter retrieves public market information and validates the returned price through the normal `ProviderRouter` quality path.

Storm candle retrieval remains intentionally disabled. `StormProvider.get_candles()` continues to reject OHLCV requests until a candle endpoint and payload contract are independently verified.

### Gate.io boundary

Gate.io is the primary application OHLCV provider. The existing adapter remains behind the canonical `MarketDataRequest` and `Candle` contracts, so strategy code does not depend on Gate.io payload shapes.

### Yahoo Finance boundary

Yahoo Finance is the OHLCV fallback. Existing session-gap handling remains enabled for Yahoo data, and the provider supports the current strategy timeframes including 4-hour aggregation from supported hourly source bars.

## Production LLM architecture

Phase 41 remains the authority boundary for grounding and output validation. Phase 42 adds provider runtime below that contract:

```text
Fresh CopilotMarketBrief
        ↓
GroundingBuilder
        ↓
ModelPrompt + EvidenceCitation[]
        ↓
AssistantOrchestrator
        ↓ optional
ProductionLanguageModel
        ↓
Retry / Circuit Breaker / Telemetry
        ↓
OpenAIResponsesModel
        ↓
OpenAI Responses API
        ↓
ModelReply
        ↓
Phase 41 citation + instruction validation
        ├──────────────→ valid → grounded model response
        └──────────────→ invalid/error → deterministic fallback
```

The external provider receives only the bounded `ModelPrompt` produced by the assistant layer. It receives no order-submission interface, execution gateway, position-sizing callback, live-activation callback, or risk-override interface.

## OpenAI Responses adapter

`app/assistant/providers/openai_responses.py` implements `GroundedLanguageModel` through an HTTP transport boundary.

Production request fields are intentionally limited to:

- model,
- system instructions,
- grounded textual input,
- maximum output-token budget.

The grounded textual input contains:

- routed intent,
- optional symbol,
- bounded recent user-query history,
- supplied evidence citations,
- current query.

The model is explicitly instructed to use only supplied evidence and to render every relied-upon citation ID visibly in square brackets.

No model tools are configured by the adapter.

## Runtime configuration

`AssistantRuntimeConfig` controls activation and reliability behavior. The default configuration keeps external LLM use disabled.

Primary environment variables:

```text
TRADING_ASSISTANT_LLM_ENABLED=0|1
TRADING_ASSISTANT_LLM_PROVIDER=openai
TRADING_ASSISTANT_LLM_MODEL=<allowlisted model>
TRADING_ASSISTANT_LLM_ALLOWED_MODELS=<comma-separated allowlist>
OPENAI_API_KEY=<deployment secret>
```

Additional supported controls:

```text
TRADING_ASSISTANT_LLM_TIMEOUT_SECONDS
TRADING_ASSISTANT_LLM_MAX_OUTPUT_TOKENS
TRADING_ASSISTANT_LLM_MAX_PROMPT_CHARS
TRADING_ASSISTANT_LLM_RETRY_ATTEMPTS
TRADING_ASSISTANT_LLM_RETRY_BACKOFF_SECONDS
TRADING_ASSISTANT_LLM_CIRCUIT_FAILURE_THRESHOLD
TRADING_ASSISTANT_LLM_CIRCUIT_RECOVERY_SECONDS
```

Default model allowlist in this phase:

```text
gpt-5.6-luna
gpt-5.6-terra
gpt-5.6-sol
```

Deployments may replace the allowlist through configuration. A configured model outside the allowlist fails at configuration validation.

## Secret policy

The external API key is never a repository configuration value.

Rules:

1. External LLM is disabled unless explicitly enabled.
2. When enabled, `OPENAI_API_KEY` must exist in the process environment.
3. Missing secret while enabled fails closed during application composition.
4. No API key is included in telemetry, API responses, prompt objects, documentation examples, or test fixtures representing production configuration.
5. CI does not require a real external-provider secret.

## Reliability boundary

`ProductionLanguageModel` wraps the provider model with the existing reliability primitives:

- bounded retry attempts,
- exponential retry backoff,
- provider circuit breaker,
- recovery interval,
- success/failure telemetry.

A provider exception propagates to the Phase 41 `AssistantOrchestrator`, which falls back to deterministic grounded output and records `model_error` as an assistant unknown condition. Provider failure therefore cannot change a deterministic trading decision.

## Grounding and output safety

Phase 42 does not replace any Phase 41 validation. A model response is accepted only when:

- text is non-empty,
- at least one citation is returned for evidence-backed model output,
- every returned citation exists in the supplied grounding bundle,
- citations are not duplicated,
- every cited identifier is visibly present in the response text,
- execution-oriented forbidden phrases are absent.

Rejected output falls back to deterministic content.

Every final assistant response retains:

```text
execution_authority = False
```

## Assistant observability

`AssistantTelemetry` provides a bounded in-memory operational event buffer.

Recorded event metadata:

- provider name,
- model name,
- prompt-version identifier,
- success/failure outcome,
- request latency in milliseconds,
- evidence-item count,
- output character count,
- provider-reported input token count when available,
- provider-reported output token count when available,
- error class name on failure,
- timezone-aware UTC timestamp.

Deliberately excluded:

- API keys,
- query/prompt text,
- response text,
- evidence values,
- session IDs,
- trading account details.

This prevents the observability buffer from becoming a secondary store of sensitive conversation or trading content.

## Assistant metrics API

New read-only route:

```text
GET /assistant/metrics
```

Aggregate response includes:

- calls,
- successes,
- failures,
- input token count,
- output token count,
- average latency.

Raw telemetry events are not exposed by this endpoint.

Existing assistant route remains:

```text
POST /assistant/query
```

## Application composition

`build_paper_application()` now wires the complete read-only assistant path:

```text
OpportunityPipeline
    ↓
CopilotExplainer
    ↓
CopilotMarketBrief
    ↓
AssistantOrchestrator
    ↓
Optional ProductionLanguageModel
    ↓
TradingApiService
```

The brief is rebuilt from the opportunity pipeline for each assistant request. Conversation memory therefore does not become the source of market/risk truth.

The same composition root wires source-specific market-data routers:

```text
Mapped Storm Provider ───────────────→ live_router
Mapped Gate.io Provider ─┐
                         ├───────────→ candle_router
Mapped Yahoo Provider ───┘
```

## Tests

Phase 42 adds deterministic tests for:

### Market-data policy

- Storm-only live-price role,
- Gate.io → Yahoo OHLCV ordering,
- fail-closed missing provider behavior,
- duplicate-role rejection.

### LLM provider/runtime

- Responses adapter request construction through injected transport,
- visible citation extraction,
- usage-token extraction,
- model allowlist rejection,
- deterministic-only disabled mode,
- fail-closed enabled mode without `OPENAI_API_KEY`,
- success telemetry,
- failure telemetry and circuit opening,
- read-only aggregate metrics API.

The provider/network test uses an injected fake transport. The CI result validates adapter behavior and application integration but does not claim that a real external paid model request was issued.

## CI evidence

Core Phase 42 implementation run:

```text
compileall                  PASS
Ruff                        PASS
strict mypy                 PASS — 0 issues / 288 source files
pytest                      PASS — 329 tests
branch-aware coverage       79.42%
required coverage           70%
```

## Security and authority guarantees

Phase 42 preserves these hard rules:

1. LLM activation is explicit and disabled by default.
2. Secrets are environment-only.
3. Provider/model selection is validated against configuration.
4. External-model output never becomes trading authority.
5. Citation validation occurs after the provider returns.
6. Provider failure degrades to deterministic narration.
7. Model narration cannot change `NO_TRADE`, `HOLD`, `REJECTED`, strategy qualification, core risk, portfolio, readiness, circuit-breaker, or connector decisions.
8. `app/execution` and `app/live_operation` are not modified by this phase.
9. Live execution remains disabled by default.

## Known limitations

- CI does not make a real OpenAI network call and does not validate account-specific model entitlement or billing.
- The default OpenAI HTTP adapter is synchronous and intended to sit behind the existing API/runtime boundary; future high-concurrency deployment may require an async transport or worker pool.
- Telemetry is in-memory and bounded; durable metrics/export integration can be added later without persisting prompt/response content.
- The assistant metrics endpoint exposes aggregate process-local metrics, not distributed multi-instance aggregation.
- Storm OHLCV remains intentionally unavailable until its candle API contract is verified.
- Yahoo Finance remains a fallback data adapter and should not be treated as an execution venue or authoritative live-price source in this application policy.

## Completion criteria

Phase 42 is complete only after:

- implementation branch global CI is green,
- documentation head global CI is green,
- branch diff confirms no execution/live-operation authority changes,
- pull request is merged to `main`,
- the merge commit on `main` passes global CI.
