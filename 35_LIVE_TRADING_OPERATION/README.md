# Phase 35 — Live Trading Operation Framework

## Objective

Provide the production-operation boundary that sits above the validated V3 trading core without weakening any existing strategy, risk, execution, health, or production-readiness gate.

## Components

- Live Environment Activation — `app/live_operation/activation.py`
- Exchange Production Connector — `app/live_operation/exchange_connector.py`
- Real-Time Market Scanner — `app/live_operation/realtime_market_scanner.py`
- Signal Production Pipeline — `app/live_operation/signal_production_pipeline.py`
- Execution Gateway — `app/live_operation/execution_gateway.py`
- Position Synchronization — `app/live_operation/position_synchronization.py`
- Live Risk Controller — `app/live_operation/live_risk_controller.py`
- Real-Time Monitoring — `app/live_operation/realtime_monitoring.py`
- Incident Management — `app/live_operation/incident_management.py`
- Trading Operations Dashboard — `app/live_operation/operations_dashboard.py`
- Live Operation Runbook — `docs/live_operation/LIVE_OPERATION_RUNBOOK.md`

## Non-negotiable invariants

1. Live execution is fail-closed.
2. Existing core risk approval remains mandatory; the live risk controller is an additional gate, not a replacement.
3. Production activation requires environment, go-live, health, connector, risk, and explicit-enable checks.
4. Strategy and scanner layers never submit orders directly.
5. The execution gateway is the only Phase 35 production-order submission boundary.
6. Duplicate order IDs are rejected before connector submission.
7. Position reconciliation reports mismatches and never silently overwrites local or venue state.
8. Critical unresolved incidents must block operational approval in the final runtime composition.
9. Credentials and secrets must never be committed to the repository.
10. The default production connector remains disabled until a venue-specific adapter is explicitly configured and validated.

## Target flow

Market Data -> Real-Time Scanner -> Signal Production -> Core Risk -> Live Risk -> Activation Gate -> Execution Gateway -> Exchange Connector -> Position Reconciliation -> Monitoring / Incidents / Dashboard

## Current scope

This phase establishes the production framework and safety boundaries. It does not embed exchange credentials and does not enable live trading by default.
