# Trading-System-V3.0

A modular, rule-based trading system designed for local development in PyCharm and future deployment behind an API for an Android client.

## Architecture principles

- Strategy, risk, portfolio, execution, storage, and presentation are separate concerns.
- Hard eligibility gates are separate from opportunity scoring.
- Open-position stop-loss monitoring runs at the beginning of every trading-state cycle after restart/recovery checks.
- Realized P&L is calculated from the position's total amount/notional model, with provider-specific contract rules isolated from generic portfolio logic.
- No fixed maximum number of open positions. Portfolio limits are risk, exposure, correlation, margin, leverage, and capital constraints.
- Top 10 is a ranking presentation limit, not a trade-count limit.
- Pyth is not part of the V3 data-source architecture.
- Execution mode is paper/shadow; live execution is not enabled.
- The core is UI-independent so the same Python domain can run from PyCharm, a server, or behind an Android-facing API.

## Current phase

**Phase 22.5 — Architecture Hardening and Strategy Fidelity**

Phase 22.5 hardens the existing Phase 1–22 system rather than adding live trading. It strengthens indicator/strategy evidence fidelity, pending-risk reservation, correlation accounting, atomic settlement, provider/data-quality contracts, portfolio-backtest state typing, runtime composition, packaging, and CI quality enforcement.

The current quality pipeline requires editable installation, compile checks, Ruff, strict mypy, the full pytest suite, and at least 70% branch-aware coverage across `app` and `interfaces`.

See `docs/architecture/22_5_architecture_hardening.md` for the detailed scope and invariants. Phase 22 journal/analytics remains documented in `docs/architecture/22_journal_analytics.md`.

## Run from PyCharm or terminal

Use the project root as the working directory.

Passive local status only:

```bash
python main.py
```

or explicitly:

```bash
python main.py status
```

This builds the PAPER application, reads local state, and runs passive readiness diagnostics without starting a market-data/runtime cycle.

To explicitly run one PAPER runtime cycle:

```bash
python main.py cycle
```

The runtime may request market data, but it still cannot submit live orders. The paper-selection queue is empty unless a caller explicitly places selected PAPER orders into it; Top-10 opportunities are never auto-submitted.

Optional paths:

```bash
python main.py status --db data/trading_system_v3.db --universe config/universe.json
```

## Risk constants

The initial policy is:

- Maximum risk per trade: **1.0% of equity**
- Maximum aggregate open risk: **4.0% of equity**
- Storm-specific maximum SL loss relative to position amount: **10%**
- No fixed maximum open-position count
- Minimum R:R: **2.5**
- Minimum score: **90 / 100**
- Minimum confidence: **90%**

These are policy defaults and must be enforced by the risk/strategy layers, not scattered across UI code.

## Strategy evidence

The V3 analysis/evidence stack includes EMA 20/50/200, SMA 50, RSI 14, MACD, ATR 14, ADX 14, Supertrend direction, rolling VWAP, volume confirmation, and Bollinger Bands.

The opportunity score remains a 100-point ranking model after hard gates:

- HTF trend alignment: 20
- Market structure: 15
- Setup quality: 25
- Entry confirmation: 15
- Volume/liquidity: 10
- Volatility quality: 5
- R:R quality: 10

Score and confidence remain independent.

## Data sources

The V3 source boundary currently contains adapters for:

- Storm
- Gate.io
- Yahoo Finance
- Public/free context sources documented in `docs/architecture/19_context_engine.md`

Pyth is deliberately excluded.

The configured universe is not hard-coded by asset count; canonical instruments, provider mappings, and contract specifications are loaded from configuration.

## Safety and execution boundary

There is no live-execution adapter in the Phase 22.5 composition root. Runtime execution remains PAPER/SHADOW with explicit user/application selection before paper submission. Structural stop-loss, aggregate-risk, correlated-risk, futures-capital, and provider-specific risk rules remain separate hard gates.
