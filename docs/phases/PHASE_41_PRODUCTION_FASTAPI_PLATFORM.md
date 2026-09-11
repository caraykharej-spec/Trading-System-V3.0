# Phase 41 — Production FastAPI Platform

## Status

**IMPLEMENTED AND CI-VALIDATED ON FEATURE BRANCH**

Phase 41 replaces the production-facing HTTP transport foundation with a versioned FastAPI/ASGI platform while preserving `TradingApiService` as the transport-independent application boundary.

The legacy `interfaces/api/http.py` stdlib adapter remains available for backward compatibility. New production deployment should use the FastAPI runtime.

> Repository history also contains `PHASE_41_GROUNDED_LLM_CONVERSATION_ORCHESTRATION.md` from an earlier roadmap numbering sequence. That capability remains implemented. This document records the current roadmap's Phase 41 API-platform milestone and does not delete or reinterpret the historical assistant capability.

## Objectives

Phase 41 establishes a production API boundary with:

- FastAPI/ASGI transport;
- versioned REST routes under `/api/v1`;
- Pydantic request validation;
- OpenAPI generation;
- fail-closed production authentication policy;
- trusted-host policy;
- deny-by-default CORS;
- request IDs and security headers;
- bounded request bodies;
- per-process rate limiting;
- structured error envelopes;
- health and readiness probes;
- lifecycle-managed application resources;
- a one-worker serialized application bridge that preserves the current SQLite thread-affinity model;
- explicit separation from strategy/risk/execution authority.

## Architecture

```text
Android / Web / Operator Client
              ↓
        HTTPS ingress
              ↓
      Uvicorn / ASGI
              ↓
      FastAPI Platform
   ├── host validation
   ├── API-key policy
   ├── rate limiting
   ├── request-size guard
   ├── request ID
   ├── validation / errors
   └── OpenAPI
              ↓
 Serialized Application Worker
      (single worker thread)
              ↓
      TradingApiService
              ↓
 Existing application contracts
  market / assistant / analytics
  position / runtime / storage
```

FastAPI is an adapter. It does not calculate strategy signals, risk, portfolio approvals, position sizing, P&L policy, or order eligibility.

## Why the serialized application worker exists

The active PAPER composition uses SQLite connections with normal thread affinity and also performs blocking provider/network operations. Running those calls directly on the ASGI event loop would be incorrect, while dispatching arbitrary calls to a generic thread pool could move a SQLite-backed application between threads.

Phase 41 therefore creates the application and executes all `TradingApiService` operations on one dedicated `ThreadPoolExecutor(max_workers=1)` worker.

This provides two guarantees:

1. the application and its SQLite-backed repositories remain on the same worker thread for their lifetime;
2. blocking application/provider work does not block the ASGI event loop.

Horizontal multi-process scale is deliberately deferred until persistence, shared rate limiting, and runtime ownership are redesigned for multi-instance operation.

## Runtime entry point

`pyproject.toml` exposes:

```text
trading-api
```

which calls:

```text
interfaces.api.runtime:main
```

The default host is `127.0.0.1`, default port is `8000`, Uvicorn uses one worker, and proxy-header trust is disabled by default.

The ASGI factory is:

```python
interfaces.api.runtime.create_application()
```

Importing the module does not build the PAPER application or open a database connection. Resource creation occurs inside FastAPI lifespan startup on the serialized application worker, and `PaperApplication.close()` runs on the same worker during shutdown.

## REST endpoints

Public operational endpoints:

```text
GET /healthz
GET /readyz
GET /api/v1/health
GET /api/v1/ready
```

Application endpoints:

```text
GET  /api/v1/positions
GET  /api/v1/opportunities?limit=N
GET  /api/v1/analytics/performance
GET  /api/v1/market-data/universe-coverage
GET  /api/v1/assistant/brief
GET  /api/v1/assistant/opportunity?symbol=...
GET  /api/v1/assistant/metrics
POST /api/v1/assistant/query
POST /api/v1/runtime/cycle
```

`limit` is schema-constrained to `1..100`.

`POST /api/v1/runtime/cycle` is **disabled by default**. It returns `403 RUNTIME_ACTION_DISABLED` unless explicitly enabled by policy. Enabling it is only valid when API-key authentication is also required.

No live-order endpoint is exposed.

## Authentication policy

Development/test environments may intentionally run without API-key auth for local work.

Production is fail-closed:

```text
TRADING_API_ENV=production
        ↓
API key required
        ↓
explicit host allowlist required
        ↓
missing/invalid configuration → startup failure
```

The configured header defaults to:

```text
X-API-Key
```

The raw key is not used as a rate-limit identity. The middleware hashes it with SHA-256 before using it as an in-process identity key.

API-key validation uses constant-time `hmac.compare_digest`.

OpenAPI explicitly declares the configured API-key header for protected operations when authentication is required.

## Host and CORS policy

Development defaults may permit `*` hosts for local use.

Production rejects wildcard host configuration and requires an explicit allowlist through:

```text
TRADING_API_ALLOWED_HOSTS=api.example.com
```

CORS is disabled unless explicit origins are configured:

```text
TRADING_API_CORS_ORIGINS=https://app.example.com
```

Credentials are not enabled by the CORS middleware.

## Request controls

Every versioned request passes through the platform middleware.

Controls include:

- fixed-window per-process request limiting;
- `Retry-After` on `429`;
- body-size guard using configured maximum `Content-Length`;
- generated or validated request IDs;
- `Cache-Control: no-store`;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`.

The rate limiter is intentionally described as **per-process**. A future horizontally scaled deployment must use ingress/shared rate limiting rather than treating this local limiter as distributed state.

## Validation and error contract

Pydantic models validate request bodies. Query/path validation errors are normalized to the API error envelope rather than leaking framework internals.

Error shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "request path, query parameters, or body failed validation"
  }
}
```

Unexpected exceptions return a generic `INTERNAL_ERROR`; exception detail is not returned to clients.

## OpenAPI and docs

Development/test defaults expose:

```text
GET /openapi.json
GET /docs
```

Production disables docs/OpenAPI by default. Operators may change that policy explicitly, but authentication and host requirements remain fail-closed.

## Configuration

Primary environment variables:

```text
TRADING_API_ENV=development|test|production
TRADING_API_HOST=127.0.0.1
TRADING_API_PORT=8000
TRADING_API_LOG_LEVEL=info
TRADING_API_PREFIX=/api/v1
TRADING_API_DOCS_ENABLED=0|1
TRADING_API_REQUIRE_KEY=0|1
TRADING_API_KEY=<secret from environment/secret manager>
TRADING_API_KEY_HEADER=X-API-Key
TRADING_API_REQUEST_ID_HEADER=X-Request-ID
TRADING_API_ALLOWED_HOSTS=localhost,api.example.com
TRADING_API_CORS_ORIGINS=https://app.example.com
TRADING_API_RATE_LIMIT_REQUESTS=120
TRADING_API_RATE_LIMIT_WINDOW_SECONDS=60
TRADING_API_MAX_BODY_BYTES=16384
TRADING_API_RUNTIME_CYCLE_ENABLED=0|1
TRADING_DB_PATH=data/trading_system_v3.db
TRADING_UNIVERSE_PATH=config/universe.json
TRADING_INITIAL_EQUITY=10000
```

No secret is committed to the repository.

## Realtime transport boundary

Phase 41 implements the production REST/ASGI platform. It does **not** create a client-facing SSE/WebSocket event stream by polling application services independently.

The existing Gate.io WebSocket is a provider-ingress market-data connection and is not a client API.

A future realtime client transport should be added only after a shared application event/snapshot bus is defined so REST, Android, dashboards, SSE and WebSocket consumers observe one canonical state stream rather than starting parallel scans or provider reads.

## Deployment boundary

Phase 41 is a production transport/runtime foundation, not a claim that the full trading system is live-trading ready.

Current deployment assumptions:

- one API process / one Uvicorn worker;
- SQLite-backed application state;
- process-local rate limiting;
- TLS termination and network-layer controls belong at the production ingress/reverse proxy;
- live venue execution remains disabled unless a separate venue connector is implemented, validated and explicitly enabled through all existing safety gates.

## Backward compatibility

`interfaces/api/http.py` remains in the repository so existing tests/tools are not broken by the transport migration.

Both adapters delegate to `TradingApiService`; business logic must not diverge between them.

## Safety boundary

Phase 41 does not change:

- strategy scoring;
- statistical qualification;
- risk approval;
- portfolio gates;
- position sizing;
- PAPER authorization;
- live-operation circuit breakers;
- venue execution behavior.

FastAPI has no direct reference to an execution gateway or venue order connector.

`/runtime/cycle` invokes only the already-configured application cycle callback and is disabled by default at the production API policy layer.

## Tests

Phase 41 tests cover:

- versioned REST health and OpenAPI;
- delegation to the existing service contract;
- normalized validation failures;
- API-key fail-closed behavior;
- OpenAPI security declaration;
- runtime-cycle disabled-by-default behavior;
- authenticated runtime-cycle opt-in;
- rate limiting and window reset;
- payload-size rejection;
- request/security headers;
- production configuration failure when auth/host requirements are missing;
- refusal to enable runtime mutation without auth;
- creation, request execution and cleanup on the same serialized application thread.

## Feature-head validation

Validated core feature head `09a6cf7082c4d392d9bfb26d3c42a8315ce57af9`:

```text
compileall: PASS
Ruff:       PASS
mypy:       PASS — 0 issues in 300 source files
pytest:     PASS — 375 tests
coverage:   79.54% (required: 70%)
```

The final documentation head, pull-request head, and merged `main` must also pass `CI / quality` before Phase 41 is closed.
