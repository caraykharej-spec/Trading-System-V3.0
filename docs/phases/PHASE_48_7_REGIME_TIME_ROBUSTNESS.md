# Phase 48.7 — Regime & Time Robustness

Status: IMPLEMENTATION IN REVIEW

This phase qualifies whether a locked strategy remains robust across externally
labelled market regimes and across chronological evaluation slices. It does not
classify regimes itself; regime identity is supplied by the upstream market
analysis/regime layer so the robustness validator remains independent from the
classifier that produced the labels.

Input slices are finite, uniquely identified, strictly non-overlapping time
intervals with an externally supplied regime, comparable higher-is-better score,
and sample count. The global and per-regime scores are sample-weighted, while
time robustness treats chronological slices as separate eras so a strong long
period cannot hide a weak neighboring period.

Qualification is fail-closed on insufficient regime diversity, insufficient time
coverage, overlapping intervals, non-finite scores, non-positive aggregate score,
or excessive slice cardinality. PASS additionally requires minimum replication
per regime, a minimum regime-relative score, bounded best/worst regime spread,
a minimum stable-time fraction, bounded worst time degradation, and a bounded
run of consecutive weak windows.

All evidence is canonically ordered by time and regime and sealed with SHA-256,
so equivalent evidence produces the same qualification identity regardless of
input ordering. The fingerprint is intended for inclusion in Phase 48.9 final
statistical qualification evidence. Research/PAPER only.
