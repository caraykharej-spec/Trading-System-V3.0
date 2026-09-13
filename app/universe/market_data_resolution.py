from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from time import perf_counter

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.adaptive_failover import AdaptiveSourceHealth
from app.data.providers.gateio import GateIOProvider
from app.data.providers.gateio_futures import GateIOFuturesProvider
from app.data.providers.gateio_tradfi import GateIOTradFiProvider
from app.data.providers.http import ProviderError
from app.data.providers.yahoo import YahooFinanceProvider
from app.data.source_registry import SourceMappingRegistry, SourceRoute
from app.universe.gateio_discovery import GateIOSpotDiscoveryProvider
from app.universe.contract_specs import ContractSpec
from app.universe.instrument import Instrument
from app.universe.symbol_mapping import SymbolMapping
from app.universe.storm_discovery import (
    StormReferenceAsset,
    StormReferenceUniverseProvider,
)


class ResolutionSource(str, Enum):
    GATEIO = "gateio"
    YFINANCE = "yfinance"
    NO_DATA = "no_data"


@dataclass(frozen=True)
class AssetDataResolution:
    base_asset: str
    canonical_symbol: str
    storm_reference_price: Decimal
    storm_provider_symbol: str
    source: ResolutionSource
    provider_symbol: str | None
    provider_price: Decimal | None
    price_deviation_percent: Decimal | None
    reason: str
    market_data_source: str | None = None
    price_multiplier: Decimal = Decimal("1")
    source_routes: tuple[SourceRoute, ...] = ()


@dataclass(frozen=True)
class UniverseCoverageReport:
    generated_at: datetime
    reference_storm: int
    gateio: int
    yfinance: int
    no_data: int
    resolved: int
    coverage_percent: Decimal
    assets: tuple[AssetDataResolution, ...]

    @classmethod
    def from_assets(
        cls, assets: tuple[AssetDataResolution, ...]
    ) -> UniverseCoverageReport:
        reference_storm = len(assets)
        gateio = sum(item.source is ResolutionSource.GATEIO for item in assets)
        yfinance = sum(item.source is ResolutionSource.YFINANCE for item in assets)
        no_data = sum(item.source is ResolutionSource.NO_DATA for item in assets)
        if gateio + yfinance + no_data != reference_storm:
            raise ValueError("universe coverage buckets must equal the Storm reference universe")
        resolved = gateio + yfinance
        coverage = (
            (Decimal(resolved) / Decimal(reference_storm) * Decimal("100"))
            if reference_storm
            else Decimal("0")
        )
        return cls(
            generated_at=datetime.now(timezone.utc),
            reference_storm=reference_storm,
            gateio=gateio,
            yfinance=yfinance,
            no_data=no_data,
            resolved=resolved,
            coverage_percent=coverage.quantize(Decimal("0.01")),
            assets=assets,
        )

    def symbol_mappings(self) -> tuple[SymbolMapping, ...]:
        """Build read-only provider mappings for the resolved live universe."""

        mappings: list[SymbolMapping] = []
        for item in self.assets:
            mappings.append(
                SymbolMapping(
                    item.canonical_symbol, "storm", item.storm_provider_symbol
                )
            )
            if item.provider_symbol is not None:
                provider = item.market_data_source or (
                    "gateio" if item.source is ResolutionSource.GATEIO else "yahoo"
                )
                mappings.append(
                    SymbolMapping(
                        item.canonical_symbol, provider, item.provider_symbol
                    )
                )
        return tuple(mappings)

    def research_contract_specs(self) -> dict[str, ContractSpec]:
        """Build conservative PAPER-only specs; these never authorize execution."""

        specs: dict[str, ContractSpec] = {}
        for item in self.assets:
            price = item.provider_price or item.storm_reference_price
            if price >= Decimal("100"):
                price_tick = Decimal("0.01")
            elif price >= Decimal("1"):
                price_tick = Decimal("0.0001")
            else:
                price_tick = Decimal("0.00000001")
            quantity_step = Decimal("0.0001")
            spec = ContractSpec(
                symbol=item.canonical_symbol,
                price_tick=price_tick,
                quantity_step=quantity_step,
                min_quantity=quantity_step,
                min_notional=Decimal("5"),
                max_leverage=Decimal("1"),
            )
            spec.validate()
            specs[item.canonical_symbol.upper()] = spec
        return specs


@dataclass(frozen=True)
class _PriceMatch:
    provider_symbol: str
    price: Decimal
    deviation_percent: Decimal
    provider: str = "gateio"
    price_multiplier: Decimal = Decimal("1")


@dataclass(frozen=True)
class StormDrivenUniverseResolver:
    """Resolve Storm-reference assets to Gate.io OHLCV, then Yahoo Finance.

    Storm is authoritative for membership and the reference price. Provider
    symbols are selected by minimum price deviation, subject to a configurable
    maximum deviation and freshness constraint. Resolution never grants
    execution authority or modifies risk/contract configuration.
    """

    storm_universe: StormReferenceUniverseProvider = StormReferenceUniverseProvider()
    gate_discovery: GateIOSpotDiscoveryProvider = GateIOSpotDiscoveryProvider()
    gate_provider: GateIOProvider = GateIOProvider()
    gate_futures_provider: GateIOFuturesProvider = GateIOFuturesProvider()
    gate_tradfi_provider: GateIOTradFiProvider = GateIOTradFiProvider()
    yahoo_provider: YahooFinanceProvider = YahooFinanceProvider()
    source_registry: SourceMappingRegistry = field(
        default_factory=SourceMappingRegistry.load
    )
    source_health: AdaptiveSourceHealth = field(default_factory=AdaptiveSourceHealth)
    max_price_deviation_percent: Decimal = Decimal("5")
    max_price_age_seconds: int = 300
    comparable_gate_quotes: tuple[str, ...] = ("USDT", "USDC", "USD")
    yahoo_quote_candidates: tuple[str, ...] = ("USD", "USDT", "USDC")
    max_workers: int = 16

    def __post_init__(self) -> None:
        if self.max_price_deviation_percent <= 0:
            raise ValueError("max_price_deviation_percent must be positive")
        if self.max_price_age_seconds < 1:
            raise ValueError("max_price_age_seconds must be positive")
        if self.max_workers < 1:
            raise ValueError("max_workers must be positive")

    def resolve(self) -> UniverseCoverageReport:
        references = self.storm_universe.discover()
        gate_instruments = self.gate_discovery.discover_instruments()
        gate_prices = self.gate_provider.list_live_prices()
        comparable_quotes = {quote.upper() for quote in self.comparable_gate_quotes}
        by_base: dict[str, list[Instrument]] = {}
        for instrument in gate_instruments:
            if not instrument.tradable:
                continue
            if instrument.quote_asset.upper() not in comparable_quotes:
                continue
            by_base.setdefault(instrument.base_asset.upper(), []).append(instrument)

        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, max(1, len(references))),
            thread_name_prefix="universe-resolution",
        ) as executor:
            resolutions = tuple(
                executor.map(
                    lambda reference: self._resolve_asset(
                        reference, by_base, gate_prices
                    ),
                    references,
                )
            )
        return UniverseCoverageReport.from_assets(resolutions)

    def get_candles(
        self,
        resolution: AssetDataResolution,
        *,
        timeframe: str,
        limit: int,
        minimum_history: int | None = None,
    ) -> list[Candle]:
        if resolution.source is ResolutionSource.NO_DATA or resolution.provider_symbol is None:
            raise ProviderError(f"OHLCV unresolved for {resolution.canonical_symbol}")
        routes = resolution.source_routes or (SourceRoute(
            provider=resolution.market_data_source or (
                "gateio" if resolution.source is ResolutionSource.GATEIO else "yahoo"
            ),
            symbol=resolution.provider_symbol,
            price_multiplier=resolution.price_multiplier,
        ),)
        failures: list[str] = []
        for route in routes:
            if not self.source_health.available(route.provider, route.symbol):
                failures.append(f"{route.provider}:circuit_open")
                continue
            try:
                started = perf_counter()
                candles = self._provider(route.provider).get_candles(
                    MarketDataRequest(route.symbol, timeframe, limit)
                )
                elapsed = Decimal(str(perf_counter() - started))
                if elapsed > route.max_latency_seconds:
                    raise ProviderError(
                        f"latency_budget_exceeded:{elapsed:.3f}s>"
                        f"{route.max_latency_seconds}s"
                    )
                if minimum_history is not None and len(candles) < minimum_history:
                    raise ProviderError(
                        f"insufficient_history:{len(candles)}<{minimum_history}"
                    )
                if route.requires_volume and candles and not any(
                    candle.volume > 0 for candle in candles
                ):
                    raise ProviderError("volume_required_but_unavailable")
                self.source_health.success(route.provider, route.symbol)
                return [Candle(
                    symbol=resolution.canonical_symbol,
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp,
                    open=candle.open * route.price_multiplier,
                    high=candle.high * route.price_multiplier,
                    low=candle.low * route.price_multiplier,
                    close=candle.close * route.price_multiplier,
                    volume=candle.volume,
                ) for candle in candles]
            except ProviderError as exc:
                self.source_health.failure(route.provider, route.symbol, exc)
                failures.append(f"{route.provider}:{exc}")
        raise ProviderError(
            f"all_sources_failed:{resolution.canonical_symbol}:{'|'.join(failures)}"
        )

    def _resolve_asset(
        self,
        reference: StormReferenceAsset,
        gate_by_base: dict[str, list[Instrument]],
        gate_prices: dict[str, LivePrice],
    ) -> AssetDataResolution:
        preferred_match = self._registry_match(reference)
        if preferred_match is not None and self._acceptable(preferred_match):
            source = (
                ResolutionSource.YFINANCE
                if preferred_match.provider == "yahoo"
                else ResolutionSource.GATEIO
            )
            mapping = self.source_registry.get(reference.base_asset)
            configured_routes = mapping.routes if mapping is not None else ()
            ordered_routes = tuple(
                route for route in configured_routes
                if route.provider == preferred_match.provider
                and route.symbol == preferred_match.provider_symbol
            ) + tuple(
                route for route in configured_routes
                if not (
                    route.provider == preferred_match.provider
                    and route.symbol == preferred_match.provider_symbol
                )
            )
            return self._resolved(
                reference,
                source,
                preferred_match,
                routes=ordered_routes,
            )

        gate_match = self._closest_gate_match(reference, gate_by_base, gate_prices)
        if gate_match is not None and self._acceptable(gate_match):
            return self._resolved(reference, ResolutionSource.GATEIO, gate_match)

        yahoo_match = self._closest_yahoo_match(reference)
        if yahoo_match is not None and self._acceptable(yahoo_match):
            gate_reason = (
                "gateio_not_found"
                if gate_match is None
                else "gateio_price_mismatch:"
                f"{gate_match.deviation_percent.quantize(Decimal('0.01'))}%"
            )
            return self._resolved(
                reference,
                ResolutionSource.YFINANCE,
                yahoo_match,
                reason=f"{gate_reason};yfinance_closest_price_within_tolerance",
            )

        reasons: list[str] = []
        if gate_match is None:
            reasons.append("gateio_not_found")
        else:
            reasons.append(
                f"gateio_price_mismatch:{gate_match.deviation_percent.quantize(Decimal('0.01'))}%"
            )
        if yahoo_match is None:
            reasons.append("yfinance_not_found")
        else:
            reasons.append(
                f"yfinance_price_mismatch:{yahoo_match.deviation_percent.quantize(Decimal('0.01'))}%"
            )
        return AssetDataResolution(
            base_asset=reference.base_asset,
            canonical_symbol=reference.canonical_symbol,
            storm_reference_price=reference.reference_price,
            storm_provider_symbol=reference.provider_symbol,
            source=ResolutionSource.NO_DATA,
            provider_symbol=None,
            provider_price=None,
            price_deviation_percent=None,
            reason=";".join(reasons),
            market_data_source=None,
        )

    def _registry_match(self, reference: StormReferenceAsset) -> _PriceMatch | None:
        mapping = self.source_registry.get(reference.base_asset)
        if mapping is None:
            return None
        for route in mapping.routes:
            if not self.source_health.available(route.provider, route.symbol):
                continue
            try:
                live = self._provider(route.provider).get_live_price(route.symbol)
            except ProviderError as exc:
                self.source_health.failure(route.provider, route.symbol, exc)
                continue
            normalized = live.price * route.price_multiplier
            match = self._match(reference.reference_price, route.symbol, normalized)
            if match.deviation_percent <= mapping.max_price_deviation_percent:
                self.source_health.success(route.provider, route.symbol)
                return _PriceMatch(
                    provider_symbol=route.symbol,
                    price=normalized,
                    deviation_percent=match.deviation_percent,
                    provider=route.provider,
                    price_multiplier=route.price_multiplier,
                )
        return None

    def _provider(
        self, name: str
    ) -> GateIOProvider | GateIOFuturesProvider | GateIOTradFiProvider | YahooFinanceProvider:
        providers = {
            self.gate_provider.name: self.gate_provider,
            self.gate_futures_provider.name: self.gate_futures_provider,
            self.gate_tradfi_provider.name: self.gate_tradfi_provider,
            self.yahoo_provider.name: self.yahoo_provider,
        }
        try:
            return providers[name]
        except KeyError as exc:
            raise ProviderError(f"unknown market-data provider: {name}") from exc

    def _closest_gate_match(
        self,
        reference: StormReferenceAsset,
        gate_by_base: dict[str, list[Instrument]],
        gate_prices: dict[str, LivePrice],
    ) -> _PriceMatch | None:
        matches: list[_PriceMatch] = []
        for instrument in gate_by_base.get(reference.base_asset.upper(), []):
            pair = instrument.symbol.replace("/", "_").upper()
            live = gate_prices.get(pair)
            if live is None or live.price <= 0 or not self._fresh(live):
                continue
            matches.append(self._match(reference.reference_price, pair, live.price))
        return self._minimum_match(matches)

    def _closest_yahoo_match(self, reference: StormReferenceAsset) -> _PriceMatch | None:
        static_matches = self._yahoo_matches(
            reference,
            self._static_yahoo_candidates(reference.base_asset),
        )
        best_static = self._minimum_match(static_matches)
        if best_static is not None and self._acceptable(best_static):
            return best_static

        try:
            discovered = self.yahoo_provider.search_symbols(reference.base_asset, limit=8)
        except ProviderError:
            discovered = ()
        discovered_matches = self._yahoo_matches(reference, discovered)
        return self._minimum_match(static_matches + discovered_matches)

    def _yahoo_matches(
        self,
        reference: StormReferenceAsset,
        symbols: tuple[str, ...],
    ) -> list[_PriceMatch]:
        matches: list[_PriceMatch] = []
        seen: set[str] = set()
        for raw_symbol in symbols:
            symbol = raw_symbol.strip()
            upper = symbol.upper()
            if not symbol or upper in seen:
                continue
            seen.add(upper)
            try:
                live = self.yahoo_provider.get_live_price(symbol)
            except ProviderError:
                continue
            if live.price <= 0 or not self._fresh(live):
                continue
            match = self._match(reference.reference_price, symbol, live.price)
            matches.append(_PriceMatch(
                provider_symbol=match.provider_symbol,
                price=match.price,
                deviation_percent=match.deviation_percent,
                provider="yahoo",
            ))
        return matches

    def _static_yahoo_candidates(self, base_asset: str) -> tuple[str, ...]:
        base = base_asset.upper()
        candidates: list[str] = [base]
        candidates.extend(f"{base}-{quote.upper()}" for quote in self.yahoo_quote_candidates)

        if len(base) == 3 and base.isalpha():
            candidates.append(f"{base}USD=X")
        if len(base) == 6 and base.isalpha():
            candidates.append(f"{base}=X")

        commodity_aliases: dict[str, tuple[str, ...]] = {
            "XAU": ("GC=F", "XAUUSD=X"),
            "XAG": ("SI=F", "XAGUSD=X"),
            "USOIL": ("CL=F",),
            "UKOIL": ("BZ=F",),
        }
        candidates.extend(commodity_aliases.get(base, ()))

        result: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            upper = candidate.upper()
            if upper in seen:
                continue
            seen.add(upper)
            result.append(candidate)
        return tuple(result)

    @staticmethod
    def _minimum_match(matches: list[_PriceMatch]) -> _PriceMatch | None:
        if not matches:
            return None
        return min(matches, key=lambda item: (item.deviation_percent, item.provider_symbol))

    @staticmethod
    def _match(reference_price: Decimal, symbol: str, price: Decimal) -> _PriceMatch:
        if reference_price <= 0 or price <= 0:
            raise ValueError("reference and candidate prices must be positive")
        deviation = abs(price - reference_price) / reference_price * Decimal("100")
        return _PriceMatch(symbol, price, deviation)

    def _fresh(self, live: LivePrice) -> bool:
        now = datetime.now(timezone.utc)
        age = abs((now - live.as_of).total_seconds())
        return age <= self.max_price_age_seconds

    def _acceptable(self, match: _PriceMatch) -> bool:
        return match.deviation_percent <= self.max_price_deviation_percent

    @staticmethod
    def _resolved(
        reference: StormReferenceAsset,
        source: ResolutionSource,
        match: _PriceMatch,
        *,
        reason: str = "closest_price_within_tolerance",
        routes: tuple[SourceRoute, ...] = (),
    ) -> AssetDataResolution:
        return AssetDataResolution(
            base_asset=reference.base_asset,
            canonical_symbol=reference.canonical_symbol,
            storm_reference_price=reference.reference_price,
            storm_provider_symbol=reference.provider_symbol,
            source=source,
            provider_symbol=match.provider_symbol,
            provider_price=match.price,
            price_deviation_percent=match.deviation_percent,
            reason=reason,
            market_data_source=match.provider,
            price_multiplier=match.price_multiplier,
            source_routes=routes,
        )
