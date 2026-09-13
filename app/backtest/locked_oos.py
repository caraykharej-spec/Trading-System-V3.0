from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class LockedOOSPlan:
    dataset_sha256: str
    strategy_fingerprint: str
    config_fingerprint: str
    total_observations: int
    train_end: int
    validation_end: int
    oos_end: int
    sealed_at: datetime
    plan_sha256: str

    @property
    def train_range(self) -> range:
        return range(0, self.train_end)

    @property
    def validation_range(self) -> range:
        return range(self.train_end, self.validation_end)

    @property
    def oos_range(self) -> range:
        return range(self.validation_end, self.oos_end)

    def verify(
        self,
        *,
        dataset_sha256: str,
        strategy_fingerprint: str,
        config_fingerprint: str,
    ) -> None:
        if dataset_sha256 != self.dataset_sha256:
            raise ValueError("locked OOS dataset fingerprint changed")
        if strategy_fingerprint != self.strategy_fingerprint:
            raise ValueError("strategy changed after OOS plan was sealed")
        if config_fingerprint != self.config_fingerprint:
            raise ValueError("configuration changed after OOS plan was sealed")
        expected = _fingerprint(
            self.dataset_sha256,
            self.strategy_fingerprint,
            self.config_fingerprint,
            self.total_observations,
            self.train_end,
            self.validation_end,
            self.oos_end,
            self.sealed_at,
        )
        if expected != self.plan_sha256:
            raise ValueError("locked OOS plan fingerprint is invalid")


def _fingerprint(
    dataset_sha256: str,
    strategy_fingerprint: str,
    config_fingerprint: str,
    total_observations: int,
    train_end: int,
    validation_end: int,
    oos_end: int,
    sealed_at: datetime,
) -> str:
    payload = {
        "config": config_fingerprint,
        "dataset": dataset_sha256,
        "oos_end": oos_end,
        "sealed_at": sealed_at.astimezone(timezone.utc).isoformat(),
        "strategy": strategy_fingerprint,
        "total": total_observations,
        "train_end": train_end,
        "validation_end": validation_end,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_oos_plan(
    *,
    dataset_sha256: str,
    strategy_fingerprint: str,
    config_fingerprint: str,
    total_observations: int,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    sealed_at: datetime | None = None,
) -> LockedOOSPlan:
    if not all((dataset_sha256, strategy_fingerprint, config_fingerprint)):
        raise ValueError("dataset, strategy and config fingerprints are required")
    if total_observations < 3:
        raise ValueError("at least three observations are required")
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be in (0, 1)")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("OOS split must be non-empty")
    train_end = int(total_observations * train_fraction)
    validation_end = train_end + int(total_observations * validation_fraction)
    if train_end < 1 or validation_end <= train_end or validation_end >= total_observations:
        raise ValueError("all chronological splits must be non-empty")
    timestamp = sealed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("sealed_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    plan_hash = _fingerprint(
        dataset_sha256,
        strategy_fingerprint,
        config_fingerprint,
        total_observations,
        train_end,
        validation_end,
        total_observations,
        timestamp,
    )
    return LockedOOSPlan(
        dataset_sha256,
        strategy_fingerprint,
        config_fingerprint,
        total_observations,
        train_end,
        validation_end,
        total_observations,
        timestamp,
        plan_hash,
    )


def validate_walk_forward_boundaries(
    windows: tuple[tuple[int, int, int, int], ...],
    *,
    total_observations: int,
) -> None:
    previous_test_end = 0
    for train_start, train_end, test_start, test_end in windows:
        if not (
            0 <= train_start < train_end
            and train_end == test_start
            and test_start < test_end <= total_observations
        ):
            raise ValueError("invalid walk-forward boundary")
        if test_start < previous_test_end:
            raise ValueError("walk-forward test windows must not overlap")
        previous_test_end = test_end
