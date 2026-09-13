# Phase 48.8 — Fee, Funding, Slippage & Market Impact Robustness

Status: IMPLEMENTATION IN REVIEW

This phase qualifies whether a positive baseline strategy edge survives adverse
trading-cost assumptions. It builds on the existing deterministic backtest cost
contract and the provider-backed Storm cost evidence layer rather than creating
a second execution-cost accounting system.

The qualification input is an explicitly labelled baseline cost assumption and
a bounded set of adverse-or-equal stress scenarios. The four qualified cost
components are round-trip fee, holding-period funding, round-trip slippage and
market impact. Funding is signed because it can be a debit or a credit; an
adverse funding scenario must still move numerically toward a greater cost.

Market impact is intentionally a scenario assumption in this phase. The current
historical backtest layer does not claim order-book reconstruction or historical
exchange-level impact calibration, so an assumed impact stress must not be
reported as measured historical impact. Provider-specific limits or later
order-book evidence may be used to construct scenarios without changing the
qualification contract.

For every scenario the report records total cost, net edge, degradation from the
baseline net edge, retained edge and component-level cost increases. Input order
is canonicalized, scenario identities are unique, non-finite evidence is
rejected, execution-cost components cannot be negative, and scenario cardinality
is capped. Stress cases that improve any baseline cost component are rejected so
an allegedly adverse matrix cannot silently include favorable assumptions.

The default final gate is fail-closed: every required stress scenario must retain
the configured minimum net edge and remain within the configured maximum edge
degradation. The report is sealed with a canonical SHA-256 fingerprint for
Phase 48.9 final statistical qualification evidence. Research/PAPER only.
