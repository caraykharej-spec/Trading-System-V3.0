# Phase 48.2 — Locked OOS & Walk-Forward

Status: IMPLEMENTATION IN REVIEW

This increment freezes the dataset, strategy and configuration fingerprints
before OOS evaluation. Chronological train, validation and OOS boundaries are
part of a SHA-256 sealed plan. Any post-seal change fails closed and requires a
new experiment identity.

Default split: 60% train, 20% validation and 20% locked OOS. All segments must
be non-empty. OOS data cannot participate in parameter selection.

Walk-forward windows must be chronological, have an exact train/test boundary,
remain inside the dataset, and advance monotonically. The existing
`WalkForwardRunner` remains responsible for executing each training and OOS
segment; the Phase 48.2 contract validates its window evidence before statistical
qualification.

Closure requires regression tests, strict typing, lint, full qualification and
security scans. This remains research/PAPER-only.
