from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Callable

from app.core.enums import SystemMode
from interfaces.api.models import ApiResponse, HealthResponse


class TradingApiService:
    """Thin application-facing API service.

    The service deliberately does not implement strategy, risk, portfolio, or
    execution rules. It exposes already-authorized application callbacks to
    future HTTP/Android clients.
    """

    def __init__(
        self,
        *,
        mode: SystemMode = SystemMode.PAPER,
        version: str = "3.0.0-dev1",
        cycle_runner: Callable[[], Any] | None = None,
        positions_provider: Callable[[], list[Any]] | None = None,
        opportunities_provider: Callable[[], list[Any]] | None = None,
        analytics_provider: Callable[[], Any] | None = None,
        readiness_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._mode = mode
        self._version = version
        self._cycle_runner = cycle_runner
        self._positions_provider = positions_provider or (lambda: [])
        self._opportunities_provider = opportunities_provider or (lambda: [])
        self._analytics_provider = analytics_provider
        self._readiness_provider = readiness_provider

    def health(self) -> ApiResponse:
        response = HealthResponse("ok", self._mode.value, self._version)
        return ApiResponse.ok(response.to_dict())

    def readiness(self) -> ApiResponse:
        if self._readiness_provider is None:
            return ApiResponse.conflict(
                "READINESS_UNAVAILABLE", "readiness diagnostics are not configured"
            )
        report = self._readiness_provider()
        return ApiResponse.ok({"readiness": self._serialize(report)})

    def positions(self) -> ApiResponse:
        return ApiResponse.ok(
            {"positions": [self._serialize(item) for item in self._positions_provider()]}
        )

    def opportunities(self, limit: int = 10) -> ApiResponse:
        if limit < 1 or limit > 100:
            return ApiResponse.bad_request("INVALID_LIMIT", "limit must be between 1 and 100")
        items = self._opportunities_provider()[:limit]
        return ApiResponse.ok({"opportunities": [self._serialize(item) for item in items]})

    def performance(self) -> ApiResponse:
        if self._analytics_provider is None:
            return ApiResponse.conflict(
                "ANALYTICS_UNAVAILABLE", "performance analytics are not configured"
            )
        return ApiResponse.ok({"performance": self._serialize(self._analytics_provider())})

    def run_cycle(self) -> ApiResponse:
        if self._cycle_runner is None:
            return ApiResponse.conflict("CYCLE_UNAVAILABLE", "runtime cycle is not configured")
        result = self._cycle_runner()
        return ApiResponse.ok({"cycle": self._serialize(result)})

    @staticmethod
    def _serialize(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, dict):
            return {
                str(key): TradingApiService._serialize(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [TradingApiService._serialize(item) for item in value]
        if is_dataclass(value):
            return TradingApiService._serialize(asdict(value))
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "__dict__"):
            return TradingApiService._serialize(vars(value))
        return str(value)
