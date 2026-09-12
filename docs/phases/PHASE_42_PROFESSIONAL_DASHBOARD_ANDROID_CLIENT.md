# Phase 42 — Professional Dashboard & Android Client

## Purpose

Deliver production-oriented presentation clients on top of the Phase 41 FastAPI platform without moving trading logic into a UI.

Phase 42 has two presentation surfaces:

1. a professional same-origin web dashboard served by FastAPI;
2. a native Android client built with Kotlin and Jetpack Compose.

Both surfaces consume the same `/api/v1` contract and remain PAPER/SHADOW/read-only. Strategy, context, risk, portfolio, execution, journal calculations, market-data resolution, and assistant grounding remain backend responsibilities.

## Architecture

```text
Storm / Gate.io / Yahoo / Context Sources
                ↓
         Trading Backend
                ↓
        TradingApiService
                ↓
     FastAPI / ASGI `/api/v1`
          ┌─────┴─────┐
          ↓           ↓
 Web Dashboard     Android Client
 `/dashboard`      Kotlin / Compose
          ↓           ↓
 Presentation only / no execution authority
```

The clients do not call providers directly. They do not calculate scores, confidence, risk, leverage, position size, or execution eligibility.

## Professional web dashboard

The dashboard is packaged under `interfaces/dashboard/static` and is served by FastAPI from the same origin:

```text
GET /dashboard
GET /dashboard/assets/styles.css
GET /dashboard/assets/app.js
```

No CDN or third-party browser script is required.

### Sections

- Dashboard
- Markets
- Ranking
- Positions
- Performance
- Risk
- News Impact
- Journal
- System / Data Health

The dashboard consumes existing Phase 41 routes including health, readiness, positions, opportunities, performance, Storm-driven universe coverage, assistant brief, assistant metrics, and grounded assistant query.

Universe coverage preserves the Phase 37.1.1 reporting invariant:

```text
(reference) Storm: N
Gate.io:           G
yfinance:          Y
No Data:           U

G + Y + U = N
```

### Browser security

- API credentials are never committed or embedded in dashboard assets.
- An optional API key is stored only in browser `sessionStorage` for the current tab/session.
- Provider/API data is rendered with DOM text nodes rather than unsafe provider-controlled HTML injection.
- FastAPI adds no-store, request-id, nosniff, frame-deny, referrer and Content-Security-Policy headers.
- The dashboard can be disabled with `TRADING_API_DASHBOARD_ENABLED=0` without changing API behavior.

## Native Android client

The Android project lives under `clients/android` and is a native Kotlin/Jetpack Compose application.

### Current screens

- Dashboard
- Ranking
- Positions
- Performance
- Grounded Assistant
- Connection Settings

The same Phase 41 `/api/v1` endpoints are consumed; there is no duplicated Python/domain logic in the APK.

### Android security boundary

- `android.permission.INTERNET` is the only network permission required.
- cleartext HTTP is disabled;
- only an HTTPS API base URL is accepted by the client configuration;
- no API key is hard-coded into source, resources, Gradle configuration, or APK defaults;
- the optional API key is retained in process memory for the current app session only;
- no order, leverage, stop-loss, take-profit, position-size, risk-budget or live-trading mutation control exists.

## Build and validation

Python/FastAPI quality remains governed by the repository-wide protected `CI / quality` gate.

Android has a separate `Android / build` workflow which runs:

```bash
gradle -p clients/android testDebugUnitTest assembleDebug --stacktrace
```

and uploads the debug APK artifact as:

```text
trading-system-android-debug
```

The project deliberately uses the API 36 / AGP 8.13.2 line. Compose is pinned to the June 2026 BOM compatible with that toolchain; Compose 1.12+ requires API 37 / AGP 9.x and is outside this phase's build baseline.

## Release boundary

A CI-produced debug APK is a validation artifact, not a signed production distribution.

The following remain outside Phase 42 and belong to later infrastructure/release qualification work:

- release keystore and signing-key management;
- signed APK/AAB generation;
- Play Store publishing;
- device-farm/UI instrumentation qualification;
- background scheduling and push notifications;
- canonical client-facing SSE/WebSocket transport;
- production release analytics/crash reporting.

## Safety and execution boundary

Phase 42 does not modify `app/execution` or `app/live_operation` and does not grant execution authority to either client.

```text
Dashboard / Android request
        ↓
FastAPI
        ↓
TradingApiService
        ↓
Existing deterministic backend gates
```

Presentation clients cannot bypass strategy, context, risk, portfolio, qualification, or execution gates. Live execution remains disabled/fail-closed unless a later separately validated production connector and activation path explicitly enables it.
