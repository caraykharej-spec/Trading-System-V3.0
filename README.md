# Trading-System-V3.0

A modular, rule-based trading system designed for local development in PyCharm and future deployment behind an API for an Android client.

## Architecture principles

- Strategy, risk, portfolio, execution, storage, and presentation are separate concerns.
- Hard eligibility gates are separate from opportunity scoring.
- Open-position stop-loss monitoring runs at the beginning of every system cycle.
- Realized P&L is calculated from the position's total amount/notional model, with provider-specific contract rules isolated from generic portfolio logic.
- No fixed maximum number of open positions. Portfolio limits are risk, exposure, correlation, margin, leverage, and capital constraints.
- Top 10 is a ranking presentation limit, not a trade-count limit.
- Pyth is not part of the V3 data-source architecture.
- Initial execution mode is paper/shadow; live execution is a later, explicitly enabled capability.
- The core is UI-independent so the same Python domain can run from PyCharm, a server, or behind an Android-facing API.

## Current phase

**Phase 02 — Domain and Data Foundation**

Completed foundations include normalized instrument/live-price/OHLCV contracts, provider interfaces, live-price freshness validation, account/equity accounting, and restart-safe SQLite position persistence.

See `docs/architecture/01_foundation.md` and `docs/architecture/02_domain_data.md`.

## Run from PyCharm

Use the project root as the working directory and run:

```bash
python main.py
```

The local smoke runner is intentionally non-trading. It demonstrates the mandatory position-safety phase and account accounting before live provider integration.

## Risk constants

The initial policy is:

- Maximum risk per trade: **1.0% of equity**
- Maximum aggregate open risk: **4.0% of equity**
- Storm-specific maximum SL loss relative to position amount: **10%**
- No fixed maximum open-position count
- Minimum R:R: **2.5**

These are policy defaults and must be enforced by the risk layer, not scattered across strategy or UI code.

## Data sources

The V3 source boundary currently reserves adapters for:

- Storm
- Gate.io
- Yahoo Finance

Pyth is deliberately excluded.
