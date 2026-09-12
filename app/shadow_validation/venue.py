from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.application.opportunity_pipeline import RiskContext
from app.data.mapped_provider import MappedMarketProvider
from app.data.market_data import LivePrice
from app.data.providers.gateio import GateIOProvider
from app.data.providers.http import ProviderError
from app.data.providers.storm import StormProvider
from app.data.providers.yahoo import YahooFinanceProvider
from app.portfolio.account import Account
from app.shadow_validation.validation import ShadowValidator
from app.universe.config_loader import load_universe


class TimestampedStormProvider(StormProvider):
    """Require a venue timestamp; retrieval time cannot prove source freshness."""

    def get_live_price(self, symbol: str) -> LivePrice:
        record = self._find_market(self.list_market_records(), symbol)
        if record is None:
            raise ProviderError("Storm market not found")
        timestamp = self._extract_timestamp(record)
        if timestamp is None:
            raise ProviderError("Storm source timestamp unavailable")
        return LivePrice(symbol, self._extract_price(record), timestamp, self.name)


def build_shadow_validator(universe_path: str | Path) -> ShadowValidator:
    registry, mapper, contracts = load_universe(universe_path)

    def risk_context(symbol: str) -> RiskContext:
        # Fresh synthetic account on each evaluation; never a user's trading account.
        return RiskContext(
            Account(Decimal("10000")), [], registry.get(symbol), contracts[symbol.upper()],
            Decimal("1"), provider="STORM",
        )

    return ShadowValidator(
        MappedMarketProvider(TimestampedStormProvider(), mapper),
        (MappedMarketProvider(GateIOProvider(), mapper),
         MappedMarketProvider(YahooFinanceProvider(), mapper)),
        risk_context,
    )
