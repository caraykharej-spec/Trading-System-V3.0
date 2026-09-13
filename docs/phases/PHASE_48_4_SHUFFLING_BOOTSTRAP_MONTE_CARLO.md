# Phase 48.4 — Trade Shuffling, Bootstrap & Monte Carlo

Status: IMPLEMENTATION IN REVIEW

This phase extends the existing Monte Carlo engine with deterministic path
construction for random permutation, reverse order, worst-first ordering, loss
and win clustering, IID bootstrap and contiguous block bootstrap.

Permutation modes preserve the exact trade multiset. Bootstrap modes preserve
path length and sample only observed outcomes. Block bootstrap retains local
dependence better than IID resampling. Every stochastic path is reproducible
from its recorded seed.

Adverse ordering is evaluated through path maximum drawdown. Later integration
will feed these paths through the locked 1,000-run matrix and Phase 48.1
statistical gate. Research/PAPER only.
