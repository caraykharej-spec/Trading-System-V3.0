from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.data.market_data import Candle, LivePrice, MarketDataRequest
from app.data.providers.http import ProviderError
from app.data.quality import (
    default_candle_max_age_seconds,
    detect_price_outliers,
    validate_candles,
    validate_live_price,
)
from app.data.reliability import CircuitBreaker, call_with_retry
from app.universe.symbol_mapping import SymbolMappingError


class MarketProvider(Protocol):
    @property
    def name(self) -> str: ...

    def get_live_price(self, symbol: str) -> LivePrice: ...

    def get_candles(self, request: MarketDataRequest) -> list[Candle]: ...


@dataclass(frozen=True)
class ProviderCircuitStatus:
    name: str
    circuit_open: bool
    consecutive_failures: int


@dataclass
class ProviderRouter:
    providers: tuple[MarketProvider, ...]
    max_live_age_seconds: int = 120
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.1
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    allow_session_gap_providers: tuple[str, ...] = ("yahoo",)
    _circuits: dict[str, CircuitBreaker] = field(default_factory=dict, init=False)

    def _breaker(self, provider: MarketProvider) -> CircuitBreaker:
        name = provider.name
        if name not in self._circuits:
            self._circuits[name] = CircuitBreaker(
                failure_threshold=self.circuit_failure_threshold,
                recovery_seconds=self.circuit_recovery_seconds,
            )
        return self._circuits[name]

    def health_snapshot(self) -> tuple[ProviderCircuitStatus, ...]:
        """Return passive circuit state without making network requests."""
        result: list[ProviderCircuitStatus] = []
        for provider in self.providers:
            breaker = self._breaker(provider)
            result.append(
                ProviderCircuitStatus(
                    name=provider.name,
                    circuit_open=breaker.is_open,
                    consecutive_failures=breaker.health.consecutive_failures,
                )
            )
        return tuple(result)

    def get_live_price(
        self, symbol: str, *, now: datetime | None = None
    ) -> LivePrice:
        errors: list[str] = []
        for provider in self.providers:
            name = provider.name
            breaker = self._breaker(provider)
            try:
                breaker.before_call()
                result = call_with_retry(
                    lambda: provider.get_live_price(symbol),
                    attempts=self.retry_attempts,
                    backoff_seconds=self.retry_backoff_seconds,
                )
                quality = validate_live_price(
                    result, self.max_live_age_seconds, now=now
                )
                if not quality.valid:
                    raise ProviderError("; ".join(quality.reasons))
                breaker.record_success()
                return result
            except SymbolMappingError as exc:
                errors.append(f"{name}: unsupported symbol ({exc})")
            except Exception as exc:
                breaker.record_failure()
                errors.append(f"{name}: {exc}")
        raise ProviderError(
            f"No provider returned reliable live price for {symbol}; "
            f"{' | '.join(errors)}"
        )

    def get_candles(
        self,
        request: MarketDataRequest,
        *,
        max_age_seconds: int | None = None,
        now: datetime | None = None,
    ) -> list[Candle]:
        errors: list[str] = []
        freshness = max_age_seconds
        if freshness is None and request.timeframe is not None:
            freshness = default_candle_max_age_seconds(request.timeframe)
        for provider in self.providers:
            name = provider.name
            breaker = self._breaker(provider)
            try:
                breaker.before_call()
                candles = call_with_retry(
                    lambda: provider.get_candles(request),
                    attempts=self.retry_attempts,
                    backoff_seconds=self.retry_backoff_seconds,
                )
                quality = validate_candles(
                    candles,
                    expected_timeframe=request.timeframe,
                    max_age_seconds=freshness,
                    now=now,
                    allow_session_gaps=(
                        name.lower() in self.allow_session_gap_providers
                    ),
                ).merge(detect_price_outliers(candles))
                if not quality.valid:
                    raise ProviderError("; ".join(quality.reasons))
                breaker.record_success()
                return candles
            except SymbolMappingError as exc:
                errors.append(f"{name}: unsupported symbol ({exc})")
            except Exception as exc:
                breaker.record_failure()
                errors.append(f"{name}: {exc}")
        raise ProviderError(
            f"No provider returned reliable candles for {request.symbol}; "
            f"{' | '.join(errors)}"
        )
