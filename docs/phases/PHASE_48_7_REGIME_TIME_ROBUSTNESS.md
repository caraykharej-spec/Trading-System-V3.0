# Phase 48.7 — Regime & Time Robustness

Status: REAL EXECUTOR READY FOR SMOKE

This phase replays the unchanged strategy over every unique locked Phase 48.6
ledger and qualifies observed performance across daily market regimes and
chronological evaluation windows. The executor verifies the completed
`48.6 -> 48.3 -> 48.2` evidence chain before sealing its plan.

Regime labels are produced by the existing market regime model from the latest
fully completed 1D candle available at each decision and trade-entry timestamp.
The attribution therefore remains no-lookahead. The real runner retains the
baseline rules, data fingerprints, costs, and locked OOS/walk-forward boundaries.
It does not tune the strategy or repeat Phase 48.3 experiment labels.

Each active ledger/regime pair becomes a performance slice. Slices are ordered
inside an independent `asset|regime` series, allowing different assets to cover
the same real-world dates without being falsely rejected as overlapping. Scores
use realized regime PnL contribution and are weighted by actual trade count.

Zero-trade ledgers are not assigned a flat-equity score. They are recorded as
coverage gaps and excluded from performance scoring. Separate coverage gates
require at least five trades in each of at least two regimes and activity across
all four chronological cohorts: three walk-forward windows and locked OOS.

Qualification is fail-closed on insufficient regime diversity, insufficient time
coverage, overlapping intervals, non-finite scores, non-positive aggregate score,
or excessive slice cardinality. PASS additionally requires minimum replication
per regime, a minimum regime-relative score, bounded best/worst regime spread,
a minimum stable-time fraction, bounded worst time degradation, and a bounded
run of consecutive weak windows.

`smoke` replays every locked ledger for up to eight assets. `full` replays all
unique ledgers (194 for the current evidence chain). Ten deterministic shards
produce one canonical result per ledger. Plan, result-set, coverage, statistical
verdict, and report identities are sealed with SHA-256.

Execution completion and `robustness_passed` remain separate. A technically
complete workflow can therefore preserve a statistically negative result for
Phase 48.9 rather than hiding it behind a failed job. Research/PAPER only.
