from __future__ import annotations

from dataclasses import dataclass


class SymbolMappingError(ValueError):
    """Raised when a provider symbol mapping is missing or duplicated."""


@dataclass(frozen=True)
class SymbolMapping:
    canonical: str
    provider: str
    provider_symbol: str


class SymbolMapper:
    def __init__(self, mappings: list[SymbolMapping] | tuple[SymbolMapping, ...]) -> None:
        self._by_key: dict[tuple[str, str], SymbolMapping] = {}
        for mapping in mappings:
            key = (mapping.canonical.upper(), mapping.provider.lower())
            if key in self._by_key:
                raise SymbolMappingError(f"Duplicate mapping: {key}")
            self._by_key[key] = mapping

    def to_provider(self, canonical: str, provider: str) -> str:
        key = (canonical.upper(), provider.lower())
        mapping = self._by_key.get(key)
        if mapping is None:
            raise SymbolMappingError(f"No mapping for {canonical} on {provider}")
        return mapping.provider_symbol

    def has_mapping(self, canonical: str, provider: str) -> bool:
        return (canonical.upper(), provider.lower()) in self._by_key
