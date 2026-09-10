from __future__ import annotations

from decimal import Decimal
from itertools import product
import random

from app.strategy.rules import DEFAULT_RULES, StrategyRules

from .models import (
    ParameterDefinition,
    ParameterSet,
    ParameterSpace,
    ParameterValue,
    SearchMethod,
)


class ResearchSpaceTooLargeError(ValueError):
    """Raised when a grid would exceed the explicit experiment trial budget."""


class StrategyRuleParameterPolicy:
    """Deny-by-default allowlist for research-time strategy-rule changes."""

    _ALLOWED = frozenset({"min_rr", "min_score", "min_confidence"})

    def __init__(self, baseline: StrategyRules = DEFAULT_RULES) -> None:
        self.baseline = baseline

    def validate_definition(self, definition: ParameterDefinition) -> None:
        if definition.name not in self._ALLOWED:
            raise ValueError(f"research parameter is not approved: {definition.name}")
        for value in definition.values:
            self._validate_value(definition.name, value)

    def validate_space(self, space: ParameterSpace) -> None:
        for definition in space.definitions:
            self.validate_definition(definition)

    def validate_set(self, parameters: ParameterSet) -> None:
        for name, value in parameters.values:
            if name not in self._ALLOWED:
                raise ValueError(f"research parameter is not approved: {name}")
            self._validate_value(name, value)

    def _validate_value(self, name: str, value: ParameterValue) -> None:
        if not isinstance(value, Decimal):
            raise TypeError(f"strategy parameter {name} must use Decimal values")
        if not value.is_finite():
            raise ValueError(f"strategy parameter {name} must be finite")
        if name == "min_rr":
            if value < self.baseline.min_rr:
                raise ValueError("research cannot lower the declared minimum R:R")
            return
        if name == "min_score":
            if not self.baseline.min_score <= value <= Decimal("100"):
                raise ValueError("research min_score must stay between baseline and 100")
            return
        if name == "min_confidence":
            if not self.baseline.min_confidence <= value <= Decimal("100"):
                raise ValueError("research min_confidence must stay between baseline and 100")
            return
        raise ValueError(f"research parameter is not approved: {name}")


def _set_from_index(space: ParameterSpace, index: int) -> ParameterSet:
    if index < 0 or index >= space.combination_count:
        raise IndexError("parameter combination index out of range")
    values: dict[str, ParameterValue] = {}
    remainder = index
    for definition in reversed(space.definitions):
        remainder, value_index = divmod(remainder, len(definition.values))
        values[definition.name] = definition.values[value_index]
    return ParameterSet.from_mapping(values)


def enumerate_parameter_sets(
    space: ParameterSpace,
    *,
    method: SearchMethod,
    max_trials: int,
    seed: int,
) -> tuple[ParameterSet, ...]:
    if max_trials <= 0:
        raise ValueError("max_trials must be positive")
    definitions = space.definitions
    if not definitions:
        return (ParameterSet(),)

    combination_count = space.combination_count
    if method is SearchMethod.GRID:
        if combination_count > max_trials:
            raise ResearchSpaceTooLargeError(
                f"grid contains {combination_count} combinations but max_trials is {max_trials}"
            )
        return tuple(
            ParameterSet.from_mapping(
                {
                    definition.name: value
                    for definition, value in zip(definitions, combination)
                }
            )
            for combination in product(*(definition.values for definition in definitions))
        )

    rng = random.Random(seed)
    sample_size = min(max_trials, combination_count)
    indexes = rng.sample(range(combination_count), k=sample_size)
    return tuple(_set_from_index(space, index) for index in indexes)
