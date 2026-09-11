from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Iterable, Mapping

from app.universe.instrument import Instrument

from .models import NormalizedNewsRecord, RelevanceResult


@dataclass(frozen=True)
class AliasEntry:
    symbol: str
    aliases: tuple[str, ...]


class EntityResolver:
    def __init__(self, extra_aliases: Mapping[str, tuple[str, ...]] | None = None) -> None:
        self.extra_aliases = {key.upper(): value for key, value in (extra_aliases or {}).items()}

    def _entries(self, instruments: Iterable[Instrument]) -> tuple[AliasEntry, ...]:
        entries: list[AliasEntry] = []
        for instrument in instruments:
            aliases = {
                instrument.symbol.casefold(),
                instrument.base_asset.casefold(),
                *[value.casefold() for value in self.extra_aliases.get(instrument.symbol.upper(), ())],
            }
            entries.append(AliasEntry(instrument.symbol, tuple(sorted(alias for alias in aliases if alias))))
        return tuple(entries)

    def resolve(
        self,
        record: NormalizedNewsRecord,
        instruments: Iterable[Instrument],
    ) -> RelevanceResult:
        text = f"{record.title} {record.body}".casefold()
        hinted = set(record.symbol_hints)
        symbols: set[str] = set()
        entities: set[str] = set()
        evidence = 0
        for entry in self._entries(instruments):
            if entry.symbol.upper() in hinted:
                symbols.add(entry.symbol)
                entities.add(entry.symbol)
                evidence += 2
            for alias in entry.aliases:
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text):
                    symbols.add(entry.symbol)
                    entities.add(alias)
                    evidence += 1
        score = min(Decimal("1"), Decimal(evidence) / Decimal("3")) if evidence else Decimal("0")
        return RelevanceResult(
            symbols=tuple(sorted(symbols)),
            entities=tuple(sorted(entities)),
            score=score,
        )
