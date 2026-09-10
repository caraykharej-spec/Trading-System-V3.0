from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation
from typing import Mapping

from app.backtest.engine import BacktestEngine
from app.backtest.models import BacktestConfig, BacktestResult
from app.data.market_data import Candle

from .models import DatasetRole, ParameterSet, ParameterValue


def _decimal_parameter(name: str, value: ParameterValue) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"parameter {name} must be numeric, not bool")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"parameter {name} must be numeric") from exc


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

    def _config_for(self, parameters: ParameterSet) -> BacktestConfig:
        provided = parameters.as_dict()
        unbound = set(provided) - set(self._bindings)
        if unbound:
            raise ValueError(f"unbound research parameters: {sorted(unbound)}")

        initial_equity = self._base_config.initial_equity
        risk_per_trade_percent = self._base_config.risk_per_trade_percent
        max_aggregate_risk_percent = self._base_config.max_aggregate_risk_percent
        max_futures_capital_percent = self._base_config.max_futures_capital_percent
        commission_percent = self._base_config.commission_percent
        slippage_percent = self._base_config.slippage_percent
        spread_percent = self._base_config.spread_percent
        funding_rate_percent_per_day = self._base_config.funding_rate_percent_per_day
        allow_short = self._base_config.allow_short

        for name, value in provided.items():
            target = self._bindings[name]
            if target == "allow_short":
                if not isinstance(value, bool):
                    raise ValueError(f"parameter {name} must be bool")
                allow_short = value
                continue
            numeric = _decimal_parameter(name, value)
            if target == "initial_equity":
                initial_equity = numeric
            elif target == "risk_per_trade_percent":
                risk_per_trade_percent = numeric
            elif target == "max_aggregate_risk_percent":
                max_aggregate_risk_percent = numeric
            elif target == "max_futures_capital_percent":
                max_futures_capital_percent = numeric
            elif target == "commission_percent":
                commission_percent = numeric
            elif target == "slippage_percent":
                slippage_percent = numeric
            elif target == "spread_percent":
                spread_percent = numeric
            elif target == "funding_rate_percent_per_day":
                funding_rate_percent_per_day = numeric
            else:
                raise ValueError(f"unsupported BacktestConfig binding: {target}")

        return BacktestConfig(
            initial_equity=initial_equity,
            risk_per_trade_percent=risk_per_trade_percent,
            max_aggregate_risk_percent=max_aggregate_risk_percent,
            max_futures_capital_percent=max_futures_capital_percent,
            commission_percent=commission_percent,
            slippage_percent=slippage_percent,
            spread_percent=spread_percent,
            funding_rate_percent_per_day=funding_rate_percent_per_day,
            allow_short=allow_short,
        )

    def __call__(
        self,
        parameters: ParameterSet,
        seed: int,
        role: DatasetRole,
    ) -> BacktestResult:
        del seed  # BacktestEngine is deterministic; seed remains part of experiment provenance.
        config = self._config_for(parameters)
        return BacktestEngine(config).run(self._symbol, self._datasets[role])
