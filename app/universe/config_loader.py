from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal
from typing import Any

from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument
from app.universe.registry import InstrumentRegistry
from app.universe.symbol_mapping import SymbolMapping, SymbolMapper


class UniverseConfigError(ValueError):
    """Raised when the universe configuration is malformed."""


def load_universe(path: str | Path) -> tuple[InstrumentRegistry, SymbolMapper, dict[str, ContractSpec]]:
    config_path = Path(path)
    try:
        payload: Any = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UniverseConfigError(f"Cannot load universe config: {config_path}") from exc

    instruments: list[Instrument] = []
    for row in payload.get("instruments", []):
        try:
            instruments.append(Instrument(
                symbol=str(row["symbol"]),
                asset_class=AssetClass(str(row["asset_class"]).upper()),
                base_asset=str(row["base_asset"]),
                quote_asset=str(row["quote_asset"]),
                tradable=bool(row.get("tradable", True)),
                min_quantity=_decimal_or_none(row.get("min_quantity")),
                quantity_step=_decimal_or_none(row.get("quantity_step")),
                price_tick=_decimal_or_none(row.get("price_tick")),
            ))
        except (KeyError, ValueError, TypeError) as exc:
            raise UniverseConfigError(f"Invalid instrument row: {row!r}") from exc

    mappings = tuple(
        SymbolMapping(str(row["canonical"]), str(row["provider"]), str(row["provider_symbol"]))
        for row in payload.get("mappings", [])
    )
    specs: dict[str, ContractSpec] = {}
    for row in payload.get("contract_specs", []):
        spec = ContractSpec(
            symbol=str(row["symbol"]),
            price_tick=Decimal(str(row["price_tick"])),
            quantity_step=Decimal(str(row["quantity_step"])),
            min_quantity=Decimal(str(row["min_quantity"])),
            min_notional=_decimal_or_none(row.get("min_notional")),
            max_leverage=_decimal_or_none(row.get("max_leverage")),
        )
        spec.validate()
        specs[spec.symbol.upper()] = spec
    return InstrumentRegistry.from_instruments(instruments), SymbolMapper(mappings), specs


def _decimal_or_none(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))
