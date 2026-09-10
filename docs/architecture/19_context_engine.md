# Phase 19 — Context Engine

The context layer provides deterministic external-risk context without adding arbitrary score bonuses.

## Domain

- News: `SUPPORTIVE`, `NEUTRAL`, `ADVERSE`, `UNKNOWN`.
- Economic events: `NONE`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- Events support country, currency, actual, forecast, previous, optional symbol relevance, and calculated surprise.
- Event windows distinguish pre-event and post-event risk windows.

## Free provider strategy

V3 uses providers that can operate without a paid subscription or mandatory API key:

- Federal Reserve public RSS for U.S. monetary-policy/regulatory context.
- SEC public RSS for regulatory/filing context.
- ECB public RSS/MID feed for euro-area central-bank context.
- BLS public RSS for U.S. economic releases.
- CoinDesk, Cointelegraph, and CryptoSlate public RSS for crypto news.
- BiQuote public calendar endpoint for a no-key normalized economic-calendar feed.

Providers are adapters only. They do not make trading decisions and a provider failure does not invalidate other sources.

## Provider architecture

```text
Public RSS / Calendar
        ↓
Provider adapter
        ↓
Normalized NewsItem / EconomicEvent
        ↓
ContextEngine
        ↓
BLOCK / DELAY / ALLOW
        ↓
Risk → Portfolio → Top-N
```

No paid API key is required by the default provider set. Provider access remains best-effort and must pass the existing data-quality/freshness rules before influencing a decision.

## Gating policy

- CRITICAL events can block new trading.
- HIGH events can delay a new decision without being a hard block.
- ADVERSE news is context, not an automatic score penalty or trade block.
- Missing/stale news is `UNKNOWN`, never treated as supportive.
- Context never overrides data-quality, strategy, risk, or portfolio hard gates.

## Safety

The engine is analytical and paper/shadow compatible. It does not submit live orders and does not manufacture missing calendar/news data.
