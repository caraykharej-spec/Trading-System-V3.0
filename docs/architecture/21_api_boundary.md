# Phase 21 — API Boundary and Android-Ready Application Interface

## Purpose

Expose the existing Python application through a thin, deterministic API boundary without moving business logic into HTTP handlers or an Android client.

## Architecture

```text
Android / Web / Future Client
            |
          HTTP
            |
     interfaces/api/http.py
            |
     interfaces/api/service.py
            |
      Existing application
   strategy / risk / portfolio
   execution / runtime / storage
```

The API is an adapter. Strategy, risk, portfolio, execution, persistence, and position-management rules remain in the existing application/domain layers.

## Endpoints

- `GET /health` — service health, current system mode, and application version.
- `GET /positions` — serialized open-position view supplied by the application boundary.
- `GET /opportunities?limit=N` — serialized opportunity view; N is constrained to 1..100.
- `POST /runtime/cycle` — explicitly invokes a configured application cycle callback.

No endpoint enables live execution. Order submission remains behind the existing paper/shadow execution boundary and explicit application wiring.

## Dependency policy

The initial adapter uses Python's standard library HTTP server so the core remains dependency-free. A production deployment can later replace only this adapter with FastAPI/ASGI or another gateway without changing the domain/application contracts.

## Safety

- No credentials are accepted by these endpoints.
- No live trading endpoint is exposed.
- API errors do not leak exception details.
- Responses are JSON and use `no-store` caching semantics.
- The HTTP adapter contains routing only; it does not calculate signals, risk, position size, or P&L.

## Testing

Tests cover response serialization, validation, delegation, HTTP routing, method restrictions, and 404/400/409 behavior.
