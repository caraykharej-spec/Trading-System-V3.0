# Public Data / No-Key Policy

## Scope

The current V3 market-data and context-data boundary is intentionally based on public endpoints that do not require application API credentials.

Covered providers:

- Storm market data
- Gate.io public market data
- Yahoo Finance public chart data
- configured public RSS/Atom news feeds
- BiQuote public economic calendar

Pyth remains excluded from V3.

## Contract

Current public-data adapters must satisfy all of the following:

1. no API key, access token, client secret, password, or credential-file parameter;
2. no environment-variable lookup for provider credentials;
3. no Authorization/Bearer header construction;
4. no credential-bearing query parameter;
5. network access is read-only public data access;
6. failures are handled by quality checks, retries, circuit breakers, provider fallback and reconciliation rather than by credential fallback.

`HttpClient` deliberately exposes only a GET JSON operation with a fixed non-secret User-Agent header. It does not accept arbitrary request headers from provider adapters.

## Configuration

`config/data.yaml` declares `providers.access_policy: public_no_key`. No market-data credential section is required for application startup.

The repository may continue to ignore `.env` files and credential files as a general security precaution for future deployment, database, application-authentication or notification secrets. Those files are not dependencies of the current market/news/context data path.

## Composition

`build_paper_application()` constructs Storm, Gate.io and Yahoo providers directly without keys, tokens, credential objects or environment lookups. The PAPER/SHADOW execution boundary is unchanged.

## Future boundaries

This policy applies to public market/context ingestion. It does not pre-authorize any future private account or live-execution integration. If a later deployment component needs a secret, it must be isolated behind the security architecture for that component and must not be retrofitted into the public-data provider path.
