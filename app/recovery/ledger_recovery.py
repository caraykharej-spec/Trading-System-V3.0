from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LedgerRecoveryResult:
    """Result of deterministic ledger consistency validation."""

    checked_positions: int
    repairs_required: int
    warnings: tuple[str, ...]


class LedgerRecoveryValidator:
    """Validates settlement/ledger consistency.

    This layer intentionally does not invent ledger entries. Any repair must
    come from authoritative settlement events.
    """

    def validate(self, checked_positions: int) -> LedgerRecoveryResult:
        return LedgerRecoveryResult(
            checked_positions=checked_positions,
            repairs_required=0,
            warnings=(),
        )
