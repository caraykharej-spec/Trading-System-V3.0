from __future__ import annotations

from dataclasses import dataclass

from app.universe.instrument import AssetClass, Instrument


class InstrumentRegistryError(ValueError):
    """Raised when the instrument universe is invalid or ambiguous."""


@dataclass
class InstrumentRegistry:
    _instruments: dict[str, Instrument]

    @classmethod
    def from_instruments(cls, instruments: list[Instrument] | tuple[Instrument, ...]) -> "InstrumentRegistry":
        registry: dict[str, Instrument] = {}
        for instrument in instruments:
            instrument.validate()
            key = instrument.symbol.upper()
            if key in registry:
                raise InstrumentRegistryError(f"Duplicate instrument: {instrument.symbol}")
            registry[key] = instrument
        return cls(registry)

    def get(self, symbol: str) -> Instrument:
        key = symbol.upper()
        try:
            return self._instruments[key]
        except KeyError as exc:
            raise InstrumentRegistryError(f"Unknown instrument: {symbol}") from exc

    def maybe_get(self, symbol: str) -> Instrument | None:
        return self._instruments.get(symbol.upper())

    def all(self, *, tradable_only: bool = False) -> tuple[Instrument, ...]:
        values = tuple(self._instruments.values())
        if tradable_only:
            values = tuple(item for item in values if item.tradable)
        return tuple(sorted(values, key=lambda item: item.symbol))

    def by_asset_class(self, asset_class: AssetClass, *, tradable_only: bool = False) -> tuple[Instrument, ...]:
        return tuple(
            item for item in self.all(tradable_only=tradable_only)
            if item.asset_class is asset_class
        )
