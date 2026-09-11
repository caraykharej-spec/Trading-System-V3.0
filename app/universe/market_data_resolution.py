from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.gateio import GateIOProvider
from app.data.providers.http import ProviderError
from app.data.providers.yahoo import YahooFinanceProvider
from app.universe.gateio_discovery import GateIOSpotDiscoveryProvider
from app.universe.instrument import Instrument
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


@dataclass(frozen=True)
class _PriceMatch:
    provider_symbol: str
    price: Decimal
    deviation_percent: Decimal


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
    yahoo_provider: YahooFinanceProvider = YahooFinanceProvider()
    max_price_deviation_percent: Decimal = Decimal("5")
    max_price_age_seconds: int = 300
    comparable_gate_quotes: tuple[str, ...] = ("USDT", "USDC", "USD")
    yahoo_quote_candidates: tuple[str, ...] = ("USD", "USDT", "USDC")

    def __post_init__(self) -> None:
        if self.max_price_deviation_percent <= 0:
            raise ValueError("max_price_deviation_percent must be positive")
        if self.max_price_age_seconds < 1:
            raise ValueError("max_price_age_seconds must be positive")

    def resolve(self) -> UniverseCoverageReport:
        references = self.storm_universe.discover()
        gate_instruments = self.gate_discovery.discover_instruments()
        gate_prices = self.gate_provider.list_live_prices()
        by_base: dict[str, list[Instrument]] = {}
        for instrument in gate_instruments:
            if not instrument.tradable:
                continue
            if instrument.quote_asset.upper() not in {
                quote.upper() for quote in self.comparable_gate_quotes
            }:
                continue
            by_base.setdefault(instrument.base_asset.upper(), []).append(instrument)

        resolutions = tuple(
            self._resolve_asset(reference, by_base, gate_prices)
            for reference in references
        )
        return UniverseCoverageReport.from_assets(resolutions)

    def get_candles(
        self,
        resolution: AssetDataResolution,
        *,
        timeframe: str,
        limit: int,
    ) -> list[Candle]:
        if resolution.source is ResolutionSource.NO_DATA or resolution.provider_symbol is None:
            raise ProviderError(f"OHLCV unresolved for {resolution.canonical_symbol}")
        request = MarketDataRequest(
            symbol=resolution.provider_symbol,
            timeframe=timeframe,
            limit=limit,
        )
        if resolution.source is ResolutionSource.GATEIO:
            candles = self.gate_provider.get_candles(request)
        else:
            candles = self.yahoo_provider.get_candles(request)
        return [
            Candle(
                symbol=resolution.canonical_symbol,
                timeframe=candle.timeframe,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
            for candle in candles
        ]

    def _resolve_asset(
        self,
        reference: StormReferenceAsset,
        gate_by_base: dict[str, list[Instrument]],
        gate_prices: dict[str, LivePrice],
    ) -> AssetDataResolution:
        gate_match = self._closest_gate_match(reference, gate_by_base, gate_prices)
        if gate_match is not None and self._acceptable(gate_match):
            return self._resolved(reference, ResolutionSource.GATEIO, gate_match)

        yahoo_match = self._closest_yahoo_match(reference)
        if yahoo_match is not None and self._acceptable(yahoo_match):
            return self._resolved(reference, ResolutionSource.YFINANCE, yahoo_match)

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
        )

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
            if live is None or not self._fresh(live):
                continue
            matches.append(self._match(reference.reference_price, pair, live.price))
        return min(matches, key=lambda item: (item.deviation_percent, item.provider_symbol)) if matches else None

    def _closest_yahoo_match(self, reference: StormReferenceAsset) -> _PriceMatch | None:
        matches: list[_PriceMatch] = []
        for quote in self.yahoo_quote_candidates:
            symbol = f"{reference.base_asset}-{quote.upper()}"
            try:
                live = self.yahoo_provider.get_live_price(symbol)
            except ProviderError:
                continue
            if not self._fresh(live):
                continue
            matches.append(self._match(reference.reference_price, symbol, live.price))
        return min(matches, key=lambda item: (item.deviation_percent, item.provider_symbol)) if matches else None

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
            reason="closest_price_within_tolerance",
        )
