# Phase 48.4 — Real Trade Shuffling, Bootstrap & Monte Carlo

Status: REAL EXECUTOR READY FOR SMOKE

Phase 48.4 consumes one exact successful full Phase 48.3 summary artifact and
verifies its report and evidence fingerprints before using any trade.

Repeated Phase 48.3 evaluations are collapsed by asset, evidence split and
walk-forward window. This prevents deterministic matrix repetitions from being
misrepresented as independent observations. Zero-trade runs remain documented
in Phase 48.3 but cannot form a bootstrap trade path.

The full plan contains 10,000 deterministic simulations over observed net trade
PnL paths: random permutation, reverse, worst-first, loss clustering, win
clustering, IID bootstrap and contiguous block bootstrap.

Permutation modes preserve the observed trade multiset. Bootstrap modes sample
only observed net trade outcomes. No synthetic candle, invented trade or
forward-filled performance is introduced. Every stochastic path records its
seed, source path fingerprint and sampled-path fingerprint.

The aggregate records return percentiles, drawdown P50/P95/P99,
mean-trade-PnL confidence percentiles and ruin count. A successful run is
robustness execution evidence only; final qualification remains Phase 48.9.

Run `scope=smoke` first for 100 simulations across all seven modes. Only after
that passes should `scope=full` run all 10,000 simulations.
