# Phase 04 — Universe and Instrument Registry

## Objective

Create one canonical instrument identity layer so strategy and risk code never depends on provider-specific symbols.

## Canonical identity

The system uses `BASE/QUOTE` as the canonical symbol form. Provider-specific identifiers are resolved through `SymbolMapper`.

## Instrument metadata

An instrument carries asset class, base/quote assets, tradability, quantity constraints, and price precision metadata. Contract-specific limits belong to `ContractSpec`.

## Provider mapping

Mappings are explicit and validated for duplicates. Missing mappings are an eligibility/data-routing failure, not a reason to guess a symbol.

## Supported asset classes

- CRYPTO
- EQUITY
- COMMODITY
- FOREX

## Timeframes

The strategy/data contract reserves:

- 15m — entry confirmation
- 1h — setup context
- 4h — primary structure/trend
- 1d — macro trend

## Important rule

The configured universe starts empty in V3.0. We will populate it from verified provider catalogs rather than copying a hard-coded asset count from the legacy system. Pyth is excluded.
