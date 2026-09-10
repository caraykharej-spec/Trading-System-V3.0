from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from hashlib import sha256

from .models import ParameterSet, ParameterSpec, SearchMethod


@dataclass(frozen=True)
class ParameterSpace:
    specs: tuple[ParameterSpec, ...]
    max_combinations: int = 100_000

    def __post_init__(self) -> None:
        if not self.specs:
            raise ValueError("parameter space must contain at least one parameter")
        if self.max_combinations <= 0:
            raise ValueError("max_combinations must be positive")
        names = [spec.name for spec in self.specs]
        if len(set(names)) != len(names):
            raise ValueError("parameter names must be unique")
        if self.combination_count > self.max_combinations:
            raise ValueError(
                f"parameter space has {self.combination_count} combinations, "
                f"above safety limit {self.max_combinations}"
            )

    @property
    def combination_count(self) -> int:
        count = 1
        for spec in self.specs:
            count *= len(spec.values)
        return count

    @property
    def fingerprint(self) -> str:
        payload = "|".join(
            f"{spec.name}=" + ",".join(f"{type(value).__name__}:{value}" for value in spec.values)
            for spec in sorted(self.specs, key=lambda item: item.name)
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def candidates(
        self, *, method: SearchMethod, seed: int, max_trials: int
    ) -> tuple[ParameterSet, ...]:
        if max_trials <= 0:
            raise ValueError("max_trials must be positive")
        ordered = tuple(sorted(self.specs, key=lambda item: item.name))
        all_candidates = [
            ParameterSet.from_mapping(dict(zip((spec.name for spec in ordered), values, strict=True)))
            for values in itertools.product(*(spec.values for spec in ordered))
        ]
        if method is SearchMethod.GRID:
            if len(all_candidates) > max_trials:
                raise ValueError(
                    "GRID search would silently truncate the parameter space; "
                    "increase max_trials or use RANDOM"
                )
            return tuple(all_candidates)
        rng = random.Random(seed)
        rng.shuffle(all_candidates)
        return tuple(all_candidates[: min(max_trials, len(all_candidates))])
