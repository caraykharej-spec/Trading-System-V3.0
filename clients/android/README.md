# Trading System V3 — Android Client

Native Android presentation client for Phase 42.

## Boundary

This app is a read-only PAPER/SHADOW client of the Phase 41 FastAPI `/api/v1` contract. It does not contain strategy, scoring, risk, portfolio, position-sizing, leverage, stop-loss, take-profit, order-submission, or live-execution logic. The backend remains the source of truth.

## Screens

- Dashboard — health, readiness, Storm universe coverage, top qualified opportunities
- Ranking — `/api/v1/opportunities`
- Positions — `/api/v1/positions`
- Performance — `/api/v1/analytics/performance`
- Assistant — grounded read-only `/api/v1/assistant/query`
- Settings — HTTPS base URL and optional `X-API-Key`

## Security

- cleartext HTTP is disabled in the Android manifest;
- the client accepts only an HTTPS API base URL;
- no API key is hard-coded into source, resources, Gradle configuration, or APK defaults;
- the API key is held in process memory for the current app session only;
- the client exposes no live-order or trading-state mutation control.

## Build

CI uses Java 17, Gradle 8.13, Android API 36 and builds/tests with:

```bash
gradle -p clients/android testDebugUnitTest assembleDebug
```

The CI workflow uploads the debug APK as the `trading-system-android-debug` artifact.

A signed release APK/AAB, signing-key management, Play Store publishing, device-farm qualification, background scheduling and production push/realtime transport are intentionally outside Phase 42 and belong to later infrastructure/release qualification work.
