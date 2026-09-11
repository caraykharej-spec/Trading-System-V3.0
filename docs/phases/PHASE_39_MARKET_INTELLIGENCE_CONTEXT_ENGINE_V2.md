# Phase 39 — Market Intelligence & Context Engine V2

## Status

Implemented on `phase-39-market-intelligence-context-engine-v2` and subject to the repository-wide `CI / quality` gate before merge to `main`.

## Objective

Phase 39 upgrades the context layer from provider-supplied impact labels into a deterministic, inspectable market-intelligence pipeline while preserving the existing `ContextEngine` as the policy boundary.

The intelligence layer may enrich context evidence. It may not generate orders, bypass strategy/risk gates, or activate live execution.

## Architecture

```text
Public News / Existing NewsProvider Contract
        ↓
RawNewsRecord / Legacy Bridge
        ↓
Normalization
        ↓
Cross-source Deduplication
        ↓
Entity / Symbol Relevance
        ↓
Event Classification
        ↓
Impact + Confidence
        ↓
Canonical NewsIntelligence
        ↓
Existing NewsItem Contract
        ↓
ContextEngine Policy
        ↓
ContextAssessment
```

Macro events are enriched independently:

```text
EconomicEvent
    ↓
Currency / Symbol Inference
    ↓
Macro / Regulatory Classification
    ↓
Event Confidence
    ↓
Existing Critical/High Event Windows
```

## Implemented components

### Normalization

- whitespace and title canonicalization,
- canonical URL handling,
- removal of common tracking query parameters,
- normalized source, symbol-hint, and country fields.

### Deduplication

- exact canonical-URL matching,
- time-bounded title-token similarity,
- cross-source merge of raw IDs and source names,
- deterministic canonical record selection.

### Entity and asset relevance

`EntityResolver` maps explicit symbol hints and configurable aliases to canonical `Instrument` symbols. Unrelated content remains global/unknown rather than inventing asset relevance.

### Classification and impact

`RuleBasedIntelligenceClassifier` is the deterministic baseline implementation. It classifies context into:

- MACRO,
- REGULATORY,
- SECURITY,
- EXCHANGE,
- PROTOCOL,
- CORPORATE,
- MARKET_STRUCTURE,
- OTHER.

It emits `NewsImpact` plus a bounded confidence score. The classifier is isolated so a future NLP/LLM model can replace it without changing `ContextEngine`, strategy, or risk contracts.

### Macro-event enrichment

Economic events can infer currency from country and infer affected instruments from base/quote currency when the provider did not supply symbols. Existing explicit symbols remain authoritative.

### Historical impact evaluation

Two evidence paths are implemented:

1. directional news evaluation — forward return and directional hit rate for SUPPORTIVE/ADVERSE intelligence;
2. macro-event evaluation — forward return magnitude without inventing a directional interpretation for event surprise.

### Existing provider compatibility

`records_from_news_items()` bridges the existing `NewsProvider -> NewsItem` contract into the V2 pipeline so Phase 39 does not require replacing current RSS/provider adapters.

## Safety boundary

Phase 39 does not:

- submit orders,
- change position sizing,
- bypass strategy qualification,
- override ContextEngine critical/high event policy,
- enable a live venue connector,
- allow an LLM to control execution.

The required direction remains:

```text
Intelligence Evidence
    ↓
Context Policy
    ↓
Strategy / Qualification
    ↓
Core Risk / Portfolio
    ↓
Execution Safety Gates
```

## Validation

The Phase 39 branch passes the repository-wide compile, Ruff, strict mypy, pytest, and branch-aware coverage gates. The first complete V2 core run verified 304 passing tests, 0 mypy issues across 273 source files, and 79.52% branch-aware coverage; the subsequent macro-event historical-impact extension also passed the same global workflow.

## Deferred work

Phase 39 deliberately does not add an external LLM dependency or paid sentiment API. Future model-backed classifiers should implement the same bounded intelligence contracts and must be validated against the deterministic baseline and historical impact evidence before use.
