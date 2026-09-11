from __future__ import annotations

from dataclasses import is_dataclass
from enum import Enum
from typing import Any, Callable

from app.core.enums import SystemMode
from interfaces.api.models import ApiResponse, HealthResponse


class TradingApiService:
    """Thin application-facing API service.

    The service deliberately does not implement strategy, risk, portfolio,
    copilot/assistant reasoning, or execution rules. It exposes already-authorized
    application callbacks to future HTTP/Android clients.
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
        copilot_brief_provider: Callable[[], Any] | None = None,
        copilot_symbol_provider: Callable[[str], Any] | None = None,
        assistant_query_provider: Callable[[str, str | None], Any] | None = None,
        assistant_metrics_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._mode = mode
        self._version = version
        self._cycle_runner = cycle_runner
        self._positions_provider = positions_provider or (lambda: [])
        self._opportunities_provider = opportunities_provider or (lambda: [])
        self._analytics_provider = analytics_provider
        self._readiness_provider = readiness_provider
        self._copilot_brief_provider = copilot_brief_provider
        self._copilot_symbol_provider = copilot_symbol_provider
        self._assistant_query_provider = assistant_query_provider
        self._assistant_metrics_provider = assistant_metrics_provider

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
            return ApiResponse.bad_request(
                "INVALID_LIMIT", "limit must be between 1 and 100"
            )
        items = self._opportunities_provider()[:limit]
        return ApiResponse.ok(
            {"opportunities": [self._serialize(item) for item in items]}
        )

    def performance(self) -> ApiResponse:
        if self._analytics_provider is None:
            return ApiResponse.conflict(
                "ANALYTICS_UNAVAILABLE", "performance analytics are not configured"
            )
        return ApiResponse.ok(
            {"performance": self._serialize(self._analytics_provider())}
        )

    def assistant_brief(self) -> ApiResponse:
        if self._copilot_brief_provider is None:
            return ApiResponse.conflict(
                "COPILOT_UNAVAILABLE", "copilot market brief is not configured"
            )
        return ApiResponse.ok(
            {"assistant": self._serialize(self._copilot_brief_provider())}
        )

    def assistant_opportunity(self, symbol: str) -> ApiResponse:
        target = symbol.strip().upper()
        if not target:
            return ApiResponse.bad_request("INVALID_SYMBOL", "symbol must not be empty")
        if self._copilot_symbol_provider is None:
            return ApiResponse.conflict(
                "COPILOT_UNAVAILABLE", "copilot symbol explanation is not configured"
            )
        result = self._copilot_symbol_provider(target)
        if result is None:
            return ApiResponse.not_found(
                "COPILOT_SYMBOL_NOT_FOUND", "no copilot evidence is available for symbol"
            )
        return ApiResponse.ok({"assistant": self._serialize(result)})

    def assistant_query(self, query: str, session_id: str | None = None) -> ApiResponse:
        normalized = " ".join(query.strip().split())
        if not normalized:
            return ApiResponse.bad_request("INVALID_QUERY", "query must not be empty")
        if len(normalized) > 2000:
            return ApiResponse.bad_request(
                "INVALID_QUERY", "query must not exceed 2000 characters"
            )
        if self._assistant_query_provider is None:
            return ApiResponse.conflict(
                "ASSISTANT_UNAVAILABLE", "grounded assistant orchestration is not configured"
            )
        try:
            result = self._assistant_query_provider(normalized, session_id)
        except ValueError as exc:
            return ApiResponse.bad_request("INVALID_ASSISTANT_REQUEST", str(exc))
        return ApiResponse.ok({"assistant": self._serialize(result)})

    def assistant_metrics(self) -> ApiResponse:
        if self._assistant_metrics_provider is None:
            return ApiResponse.conflict(
                "ASSISTANT_METRICS_UNAVAILABLE", "assistant metrics are not configured"
            )
        return ApiResponse.ok(
            {"assistant_metrics": self._serialize(self._assistant_metrics_provider())}
        )

    def run_cycle(self) -> ApiResponse:
        if self._cycle_runner is None:
            return ApiResponse.conflict(
                "CYCLE_UNAVAILABLE", "runtime cycle is not configured"
            )
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
                str(key): TradingApiService._serialize(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [TradingApiService._serialize(item) for item in value]
        if is_dataclass(value) and not isinstance(value, type):
            return TradingApiService._serialize(vars(value))
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "__dict__"):
            return TradingApiService._serialize(vars(value))
        return str(value)
