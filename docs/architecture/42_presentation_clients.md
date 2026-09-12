# Presentation Clients — Dashboard and Android

## Contract ownership

Phase 42 adds presentation clients only. `TradingApiService` and the Phase 41 FastAPI `/api/v1` surface remain the shared application contract. Neither client calls Storm, Gate.io, Yahoo Finance, context providers, repositories, risk engines, or execution services directly.

```text
Backend domain/application
        ↓
TradingApiService
        ↓
FastAPI /api/v1
   ┌────┴────┐
   ↓         ↓
Web UI   Android UI
```

## Web dashboard

The same-origin dashboard is served from `/dashboard` and consumes the existing API. It presents Dashboard, Markets, Ranking, Positions, Performance, Risk, News Impact, Journal and System/Data Health views. Optional API-key state is browser-session only.

## Android client

The native Kotlin/Jetpack Compose client consumes the same API over HTTPS. It exposes Dashboard, Ranking, Positions, Performance, grounded Assistant and Connection Settings. The client contains no deterministic trading logic and no live-order surface.

## Safety invariants

1. Clients may present backend evidence but may not derive or override strategy eligibility.
2. Clients may not calculate authoritative position sizing, risk budgets, leverage or execution eligibility.
3. Clients expose no production order-submission capability in Phase 42.
4. API secrets are never hard-coded into web or Android artifacts.
5. Missing backend data remains unavailable; clients do not manufacture substitutes.
6. PAPER/SHADOW remains the supported operational mode for client workflows.

## Release boundary

The Android CI artifact is an unsigned/debug validation APK. Signing, AAB release generation, store distribution, device-farm qualification, background scheduling, push/realtime client transport and production release telemetry are later infrastructure/release concerns.
