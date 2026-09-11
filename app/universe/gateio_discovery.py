from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.data.providers.http import HttpClient, ProviderError, to_decimal
from app.universe.instrument import AssetClass, Instrument


def _step_from_precision(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        precision = int(value)
    except (TypeError, ValueError):
        return None
    if precision < 0:
        return None
    return Decimal(1).scaleb(-precision)


@dataclass(frozen=True)
class GateIOSpotDiscoveryProvider:
    """Discover public Gate.io spot markets without credentials."""

    name: str = "gateio"
    base_url: str = "https://api.gateio.ws/api/v4"
    client: HttpClient = HttpClient()
    quote_allowlist: tuple[str, ...] | None = None
    normal_pairs_only: bool = True

    def discover_instruments(self) -> tuple[Instrument, ...]:
        payload = self.client.get_json(f"{self.base_url}/spot/currency_pairs")
        if not isinstance(payload, list):
            raise ProviderError("Gate.io currency-pair discovery returned invalid payload")

        allowed_quotes = (
            {quote.upper() for quote in self.quote_allowlist}
            if self.quote_allowlist is not None
            else None
        )
        instruments: list[Instrument] = []
        for record in payload:
            if not isinstance(record, dict):
                continue
            base = str(record.get("base") or "").upper()
            quote = str(record.get("quote") or "").upper()
            if not base or not quote:
                continue
            if allowed_quotes is not None and quote not in allowed_quotes:
                continue
            if self.normal_pairs_only and str(record.get("type") or "normal") != "normal":
                continue

            trade_status = str(record.get("trade_status") or "untradable")
            min_quantity = None
            raw_min_quantity = record.get("min_base_amount")
            if raw_min_quantity not in (None, ""):
                parsed = to_decimal(raw_min_quantity)
                min_quantity = parsed if parsed >= 0 else None

            instruments.append(
                Instrument(
                    symbol=f"{base}/{quote}",
                    asset_class=AssetClass.CRYPTO,
                    base_asset=base,
                    quote_asset=quote,
                    tradable=trade_status == "tradable",
                    min_quantity=min_quantity,
                    quantity_step=_step_from_precision(record.get("amount_precision")),
                    price_tick=_step_from_precision(record.get("precision")),
                )
            )

        return tuple(sorted(instruments, key=lambda item: item.symbol))
