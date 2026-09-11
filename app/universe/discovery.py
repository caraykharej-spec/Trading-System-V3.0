from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.universe.instrument import Instrument
from app.universe.registry import InstrumentRegistry


class InstrumentDiscoveryProvider(Protocol):
    @property
    def name(self) -> str: ...

    def discover_instruments(self) -> tuple[Instrument, ...]: ...


@dataclass(frozen=True)
class UniverseDiscoveryResult:
    instruments: tuple[Instrument, ...]
    providers: tuple[str, ...]
    errors: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    @property
    def healthy(self) -> bool:
        return bool(self.instruments) and not self.errors and not self.conflicts

    def build_registry(self) -> InstrumentRegistry:
        return InstrumentRegistry.from_instruments(self.instruments)


class DynamicUniverseDiscovery:
    """Discover and reconcile canonical instruments from provider metadata."""

    def __init__(self, providers: tuple[InstrumentDiscoveryProvider, ...]) -> None:
        if not providers:
            raise ValueError("at least one discovery provider is required")
        self.providers = providers

    def discover(self, *, tradable_only: bool = True) -> UniverseDiscoveryResult:
        merged: dict[str, Instrument] = {}
        contributing: list[str] = []
        errors: list[str] = []
        conflicts: list[str] = []

        for provider in self.providers:
            try:
                instruments = provider.discover_instruments()
            except Exception as exc:
                errors.append(f"{provider.name}: {exc}")
                continue

            contributing.append(provider.name)
            for instrument in instruments:
                instrument.validate()
                if tradable_only and not instrument.tradable:
                    continue
                key = instrument.symbol.upper()
                existing = merged.get(key)
                if existing is not None and existing != instrument:
                    conflicts.append(
                        f"{key}: conflicting metadata from provider {provider.name}"
                    )
                    continue
                merged[key] = instrument

        instruments = tuple(sorted(merged.values(), key=lambda item: item.symbol))
        return UniverseDiscoveryResult(
            instruments=instruments,
            providers=tuple(contributing),
            errors=tuple(errors),
            conflicts=tuple(conflicts),
        )
