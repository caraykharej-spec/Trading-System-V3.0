from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from app.application.opportunity_pipeline import OpportunityPipeline, RiskContextLoader
from app.application.strategy_pipeline import StrategyPipeline
from app.context.context_engine import ContextEngine
from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.provider_router import MarketProvider
from app.data.quality import (
    default_candle_max_age_seconds,
    detect_price_outliers,
    timeframe_seconds,
    validate_candles,
    validate_live_price,
)
from app.market.analysis import MarketSnapshot, analyze_market

TIMEFRAMES = ("1d", "4h", "1h", "15m")


def canonical_json(value: object) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class ShadowReport:
    status: str
    observed_at: str
    symbols: tuple[str, ...]
    checks: tuple[dict[str, object], ...]
    data_digest: str | None = None
    decision_digest: str | None = None
    decisions: dict[str, object] | None = None
    schema_version: int = 1
    scope: str = "READ_ONLY_VENUE_SHADOW_INTEGRATION"
    execution_enabled: bool = False
    context_scope: str = "EMPTY_NEWS_AND_EVENTS_NOT_LIVE_VALIDATED"

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, sort_keys=True, indent=2)


class ShadowValidator:
    """Capture once, evaluate twice; no runtime, executor, DB or order queue.

    PASS proves bounded data/decision integration only, never live readiness,
    profitability, context-feed coverage or venue account reconciliation.
    """

    def __init__(
        self,
        price_provider: MarketProvider,
        candle_providers: tuple[MarketProvider, ...],
        risk_context_loader: RiskContextLoader,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if price_provider.name != "storm":
            raise ValueError("live price source must be storm")
        if tuple(p.name for p in candle_providers) != ("gateio", "yahoo"):
            raise ValueError("OHLCV source order must be gateio then yahoo")
        self.price_provider = price_provider
        self.candle_providers = candle_providers
        self.risk_context_loader = risk_context_loader
        self.clock = clock

    def run(self, symbols: tuple[str, ...]) -> ShadowReport:
        if not 1 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols):
            raise ValueError("provide 1..10 unique canonical symbols")
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("clock must be timezone-aware")
        checks: list[dict[str, object]] = []
        captured: dict[str, tuple[Candle, ...]] = {}
        prices: dict[str, LivePrice] = {}
        for symbol in symbols:
            try:
                price = self.price_provider.get_live_price(symbol)
                quality = validate_live_price(price, now=self.clock())
                if price.symbol != symbol or price.provider != "storm" or not quality.valid:
                    raise ValueError("invalid Storm identity/freshness/price")
                prices[symbol] = price
                checks.append({"symbol": symbol, "kind": "live_price", "status": "PASS",
                               "provider": "storm", "as_of": price.as_of.isoformat()})
            except Exception as exc:
                checks.append({"symbol": symbol, "kind": "live_price", "status": "HOLD",
                               "reason": type(exc).__name__})
            for timeframe in TIMEFRAMES:
                failures: list[str] = []
                for provider in self.candle_providers:
                    try:
                        request = MarketDataRequest(symbol, timeframe, 261)
                        raw = provider.get_candles(request)
                        observed = self.clock()
                        step = timedelta(seconds=timeframe_seconds(timeframe))
                        # An active candle may be returned by public APIs; never use it.
                        if any(c.timestamp > observed for c in raw):
                            raise ValueError("future candle")
                        candles = tuple(c for c in raw if c.timestamp + step <= observed)
                        if len(candles) < 260:
                            raise ValueError("insufficient closed history")
                        if any(c.symbol != symbol for c in candles):
                            raise ValueError("candle symbol mismatch")
                        quality = validate_candles(
                            candles, expected_timeframe=timeframe, now=observed,
                            max_age_seconds=default_candle_max_age_seconds(timeframe),
                            require_complete_last_candle=True,
                            allow_session_gaps=provider.name == "yahoo",
                        ).merge(detect_price_outliers(candles))
                        if not quality.valid or any(
                            min(c.open, c.high, c.low, c.close) <= Decimal("0")
                            for c in candles
                        ):
                            raise ValueError("invalid closed OHLCV")
                        captured[f"{symbol}:{timeframe}"] = candles[-260:]
                        checks.append({"symbol": symbol, "timeframe": timeframe,
                                       "status": "PASS", "provider": provider.name,
                                       "count": 260, "fallback_reasons": failures,
                                       "warnings": quality.warnings})
                        break
                    except Exception as exc:
                        failures.append(f"{provider.name}:{type(exc).__name__}")
                else:
                    checks.append({"symbol": symbol, "timeframe": timeframe,
                                   "status": "HOLD", "reason": failures})
        # Recheck the prices after all network reads: a slow batch is not fresh evidence.
        for symbol, price in prices.items():
            if not validate_live_price(price, now=self.clock()).valid:
                checks.append({"symbol": symbol, "status": "HOLD",
                               "reason": "price expired during capture"})
        if any(c["status"] != "PASS" for c in checks):
            return ShadowReport("HOLD", now.isoformat(), symbols, tuple(checks))
        data_digest = fingerprint({
            "prices": {s: asdict(p) for s, p in prices.items()},
            "candles": {k: [asdict(c) for c in v] for k, v in captured.items()},
        })

        def snapshots(symbol: str) -> tuple[
            MarketSnapshot, MarketSnapshot, MarketSnapshot, MarketSnapshot
        ]:
            values = [analyze_market(symbol, tf, list(captured[f"{symbol}:{tf}"]))
                      for tf in TIMEFRAMES]
            return values[0], values[1], values[2], values[3]

        def evaluate() -> dict[str, object]:
            pipeline = OpportunityPipeline(
                StrategyPipeline(snapshots), self.risk_context_loader,
                context_loader=lambda symbol: ContextEngine().assess(symbol, now=now),
            )
            return asdict(pipeline.evaluate(symbols, top_n=len(symbols)))

        try:
            first, second = evaluate(), evaluate()
            equal = fingerprint(first) == fingerprint(second)
            checks.append({"kind": "deterministic_replay", "status": "PASS" if equal else "FAIL"})
            return ShadowReport("PASS" if equal else "FAIL", now.isoformat(), symbols,
                                tuple(checks), data_digest, fingerprint(first), first)
        except Exception as exc:
            checks.append({"kind": "shadow_pipeline", "status": "FAIL",
                           "reason": type(exc).__name__})
            return ShadowReport("FAIL", now.isoformat(), symbols, tuple(checks), data_digest)
