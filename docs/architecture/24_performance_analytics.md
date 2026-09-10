# Phase 24 — Performance & Analytics

## Purpose

Extend the read-only analytics layer into a professional evaluation framework built on persisted journal facts. Phase 24 does not alter strategy decisions, risk policy, or execution.

## Scope

The framework measures:

- trade quality and expectancy,
- equity behaviour,
- drawdown and recovery characteristics,
- holding-time distribution,
- realized R performance,
- existing setup/regime/direction/symbol/month attribution.

## Safety boundaries

Analytics is downstream only:

- no order creation,
- no strategy mutation,
- no risk override,
- no live execution path.

All metrics are derived from completed journal records.

## Integration

Phase 24 extends the existing analytics package while preserving the Phase 22 journal contract and Phase 23 research isolation.
