from __future__ import annotations

from dataclasses import fields, replace
from typing import Mapping

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, BacktestResult
from app.data.market_data import Candle

from .models import DatasetRole, ParameterSet


class BacktestResearchEvaluator:
    """Explicit bridge from controlled research parameters to BacktestConfig.

    Only parameter names listed in ``bindings`` may alter configuration. The adapter
    never mutates global strategy/risk constants or module state.
    """

    def __init__(
        self,
        *,
        symbol: str,
        datasets: Mapping[DatasetRole, dict[str, list[Candle]]],
        base_config: BacktestConfig,
        bindings: Mapping[str, str],
    ) -> None:
        if not symbol.strip():
            raise ValueError("symbol must be non-empty")
        missing_roles = set(DatasetRole) - set(datasets)
        if missing_roles:
            raise ValueError(f"missing research datasets: {sorted(role.value for role in missing_roles)}")
        valid_fields = {field.name for field in fields(BacktestConfig)}
        unknown_fields = set(bindings.values()) - valid_fields
        if unknown_fields:
            raise ValueError(f"unknown BacktestConfig fields: {sorted(unknown_fields)}")
        if len(set(bindings.values())) != len(bindings):
            raise ValueError("multiple research parameters cannot target the same config field")
        self._symbol = symbol
        self._datasets = dict(datasets)
        self._base_config = base_config
        self._bindings = dict(bindings)

    def __call__(
        self,
        parameters: ParameterSet,
        seed: int,
        role: DatasetRole,
    ) -> BacktestResult:
        del seed  # BacktestEngine is deterministic; seed remains part of experiment provenance.
        provided = parameters.as_dict()
        unbound = set(provided) - set(self._bindings)
        if unbound:
            raise ValueError(f"unbound research parameters: {sorted(unbound)}")
        updates = {
            self._bindings[name]: value
            for name, value in provided.items()
        }
        config = replace(self._base_config, **updates)
        return BacktestEngine(config).run(self._symbol, self._datasets[role])
