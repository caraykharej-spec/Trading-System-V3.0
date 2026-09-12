# API Boundary and Production FastAPI Platform

## Purpose

Expose the existing Python application through a thin transport boundary without moving business logic into HTTP handlers, FastAPI dependencies, or an Android/web client.

Phase 21 established the transport-independent `TradingApiService` and a lightweight stdlib HTTP adapter. The current Phase 41 API roadmap adds the production FastAPI/ASGI adapter while preserving that original boundary.

## Architecture

```text
Android / Web / Operator Client
            ↓
      HTTPS / ingress
            ↓
      Uvicorn / ASGI
            ↓
interfaces/api/fastapi_app.py
            ↓
 serialized application worker
            ↓
interfaces/api/service.py
            ↓
      Existing application
 strategy / context / risk
 portfolio / runtime / storage
```

The API is an adapter. Strategy, risk, portfolio, execution, persistence, position management, assistant grounding, and market-data source rules remain in their existing application/domain layers.

## Adapters

### Production adapter

`interfaces/api/fastapi_app.py`

Provides:

- FastAPI/ASGI;
- `/api/v1` route versioning;
- Pydantic validation;
- OpenAPI;
- optional API-key authentication with production fail-closed policy;
- trusted hosts;
- explicit CORS allowlist;
- request IDs and security headers;
- request-size bounds;
- process-local rate limiting;
- structured errors;
- lifespan-owned application startup/shutdown.

### Legacy compatibility adapter

`interfaces/api/http.py`

The stdlib HTTP adapter remains for compatibility and tests. It is no longer the preferred production transport.

Both adapters delegate to `TradingApiService`; transport-specific business logic is prohibited.

## Production routes

Operational probes:

```text
GET /healthz
GET /readyz
```

Versioned API:

```text
GET  /api/v1/health
GET  /api/v1/ready
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

No route submits a live venue order.

`/api/v1/runtime/cycle` is disabled by default and cannot be configured as enabled unless API-key authentication is required.

## Runtime and thread ownership

The current PAPER composition is SQLite-backed. Phase 41 therefore does not dispatch repository work across arbitrary ASGI worker threads.

The FastAPI lifespan creates one dedicated application worker thread. `build_paper_application()` is constructed on that worker, all `TradingApiService` operations execute on it, and application cleanup runs on it.

```text
ASGI event loop
     ↓
ThreadPoolExecutor(max_workers=1)
     ↓
PAPER application + SQLite repositories
```

This keeps blocking application/provider operations off the ASGI event loop while preserving the current SQLite thread-affinity contract.

## Authentication and production policy

`FastApiSettings` is fail-closed in production.

Production requires:

- API-key authentication;
- a non-wildcard trusted-host allowlist.

The default key header is `X-API-Key`. Secrets come from environment/secret management and are not committed.

OpenAPI marks protected operations with the configured API-key security scheme when authentication is enabled.

Health/readiness remain public so infrastructure probes do not require application credentials.

## Request controls

The platform adds:

- fixed-window rate limiting per process;
- `Retry-After` on `429`;
- configurable request body limit;
- request ID generation/propagation;
- `Cache-Control: no-store`;
- `X-Content-Type-Options: nosniff`;
- `X-Frame-Options: DENY`;
- `Referrer-Policy: no-referrer`.

CORS is disabled unless explicit origins are configured.

## Error contract

Errors use a stable envelope:

```json
{
  "error": {
    "code": "...",
    "message": "..."
  }
}
```

Request validation is normalized to `400 VALIDATION_ERROR`. Unexpected exceptions return generic `500 INTERNAL_ERROR`; internal exception text is not returned to clients.

## OpenAPI policy

Local development/test may expose:

```text
/docs
/openapi.json
```

Production disables API docs by default. This can be changed explicitly without weakening authentication/host validation requirements.

## Realtime client transport

The Gate.io WebSocket under `app/data/providers` is provider ingress, not a client API.

Phase 41 does not add a client SSE/WebSocket stream that independently polls the application. A client-facing realtime transport should consume a future shared application event/snapshot bus so REST, Android, dashboards and streams observe one canonical state flow.

## Horizontal scaling boundary

The current production API foundation intentionally runs one process/worker because:

- active state is SQLite-backed;
- the local rate limiter is process-local;
- application/runtime ownership is not yet distributed.

Horizontal scaling requires shared persistence/runtime coordination and a distributed or ingress rate limiter. It must not be enabled merely by increasing Uvicorn worker count.

## Safety

- FastAPI contains no strategy/risk calculations.
- No live trading endpoint is exposed.
- API-key authentication does not grant execution authority.
- Runtime-cycle exposure remains disabled by default.
- Live venue execution remains behind the existing production-readiness, live-risk, circuit-breaker, connector and explicit-enable gates.
- API failures cannot alter deterministic trading decisions.

## Testing

Tests cover route versioning, service delegation, validation, authentication, OpenAPI security metadata, runtime-action policy, rate limits, body limits, security headers, production configuration, and serialized lifecycle/thread ownership.

See `docs/phases/PHASE_41_PRODUCTION_FASTAPI_PLATFORM.md` for the phase implementation and deployment contract.
