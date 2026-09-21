# Phase 48.5 — Synthetic Paths, Noise & Data Robustness

Status: REAL EVIDENCE PIPELINE IMPLEMENTED

Synthetic research paths cover geometric Brownian motion, jump diffusion,
volatility clustering and deterministic regime switching. They are seeded,
strictly positive and finite, and cannot replace real OOS evidence.

Relative noise injection is bounded and reproducible. Explicit data-corruption
scenarios create duplicate or missing observations so downstream dataset quality
gates can prove fail-closed behavior.

Synthetic results must be labelled as synthetic, retain model parameters and
seed, and remain separate from provider-backed historical performance.
Research/PAPER only.

The real workflow consumes one exact successful full Phase 48.4 artifact and
verifies the complete Phase 48.4 -> Phase 48.3 fingerprint chain. It then runs
10,000 deterministic scenarios across ten shards:

- observed-trade entry/exit price perturbations at 5, 10, 25 and 50 bps;
- GBM, jump-diffusion, volatility-cluster and regime-switching path diagnostics;
- duplicate and missing-ledger corruption gates that must fail closed.

Repeated Phase 48.3 matrix evaluations are collapsed to unique
asset/split/window ledgers before scenario construction. A 100-scenario smoke
covers all eight modes. Synthetic paths are reported as market diagnostics,
not strategy returns, because this artifact does not regenerate trading
signals on synthetic candles. Price-noise results preserve observed trades and
recompute net PnL after perturbing entry and exit prices. This remains execution
evidence; Phase 48.9 owns the final statistical verdict.
