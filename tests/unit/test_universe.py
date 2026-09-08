from decimal import Decimal

import pytest

from app.universe.contract_specs import ContractSpec
from app.universe.instrument import AssetClass, Instrument
from app.universe.registry import InstrumentRegistry, InstrumentRegistryError
from app.universe.symbol_mapping import SymbolMapping, SymbolMapper, SymbolMappingError


def btc() -> Instrument:
    return Instrument(
        symbol="BTC/USDT",
        asset_class=AssetClass.CRYPTO,
        base_asset="BTC",
        quote_asset="USDT",
        quantity_step=Decimal("0.0001"),
        price_tick=Decimal("0.01"),
    )


def test_registry_is_case_insensitive_and_sorted() -> None:
    registry = InstrumentRegistry.from_instruments([btc()])
    assert registry.get("btc/usdt").symbol == "BTC/USDT"
    assert registry.all()[0].symbol == "BTC/USDT"


def test_registry_rejects_duplicates() -> None:
    with pytest.raises(InstrumentRegistryError):
        InstrumentRegistry.from_instruments([btc(), btc()])


def test_symbol_mapper_resolves_provider_symbol() -> None:
    mapper = SymbolMapper((SymbolMapping("BTC/USDT", "gateio", "BTC_USDT"),))
    assert mapper.to_provider("btc/usdt", "GATEIO") == "BTC_USDT"


def test_symbol_mapper_rejects_missing_mapping() -> None:
    mapper = SymbolMapper(())
    with pytest.raises(SymbolMappingError):
        mapper.to_provider("BTC/USDT", "storm")


def test_contract_spec_validation() -> None:
    spec = ContractSpec(
        symbol="BTC/USDT",
        price_tick=Decimal("0.01"),
        quantity_step=Decimal("0.0001"),
        min_quantity=Decimal("0.001"),
        max_leverage=Decimal("10"),
    )
    spec.validate()
