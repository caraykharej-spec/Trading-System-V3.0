# Phase 48.6 — Parameter Sensitivity & Stability

Status: IMPLEMENTATION IN REVIEW

This phase qualifies local parameter robustness with deterministic, bounded
one-at-a-time sweeps around the locked baseline configuration. Relative-percent
perturbations cover ordinary positive parameters, while absolute perturbations
support zero-valued or signed parameters without introducing special cases.

Each parameter is evaluated against four fail-closed stability gates: finite
outputs, maximum permitted degradation, minimum stable-neighborhood fraction,
and maximum adjacent performance cliff. Bound clipping is deterministic and
colliding clipped scenarios are deduplicated before evaluation. Total scenario
cardinality is capped to prevent accidental combinatorial or runtime expansion.

The report uses a canonical parameter ordering and a SHA-256 evidence
fingerprint over thresholds, sweep definitions, evaluated points, metrics and
the final PASS/FAIL decision. Equivalent ordered evidence therefore produces a
reproducible qualification identity suitable for the later Phase 48.9 final
statistical report. Research/PAPER only.
