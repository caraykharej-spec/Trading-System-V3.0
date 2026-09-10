# Dependency Rules

## Layer Direction

Allowed dependency direction:

```
Interfaces
    |
Application
    |
Domain Modules
    |
Core / Contracts
```

## Rules

- Core must not import application, interfaces, dashboard, or exchange adapters.
- Contracts are the only shared language between domain boundaries.
- Strategy must not directly execute orders.
- Risk must not depend on presentation layers.
- Dashboard and API layers consume application services only.
- Execution adapters are isolated behind execution contracts.

## Forbidden Examples

```
Risk -> Dashboard
Strategy -> Storm API
Core -> Streamlit
```

## Required Flow

```
Market Data
 -> Scanner
 -> Strategy
 -> Risk
 -> Execution
 -> Portfolio
 -> Journal
```
