# Phase 48.3 — 1000-Run Matrix & Reproducibility

Status: IMPLEMENTATION IN REVIEW

The qualification matrix is the exact Cartesian product of locked dataset
versions, evidence splits, random seeds, strategy fingerprints, configuration
fingerprints and cost scenarios. Its cardinality must equal 1,000; undersized or
oversized matrices fail before execution.

Every experiment receives a SHA-256 identity derived from all matrix dimensions.
Storage labels are not evidence identity. Duplicate identities, unordered
indexes and missing runs fail closed.

Executors return canonical bytes. Each result is content-fingerprinted, and the
ordered matrix and complete evidence set receive separate SHA-256 fingerprints.
Concurrency cannot change either fingerprint. Failed runs remain in evidence
with their exception type and message; they are never silently dropped or
replaced by successful runs.

This phase proves the runner contract with 1,000 lightweight deterministic
executions. It does not claim strategy profitability. Real backtest outcomes
will be connected to this runner in subsequent robustness phases and evaluated
by the statistical gate established in Phase 48.1.
