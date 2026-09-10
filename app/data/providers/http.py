from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """Raised when a market-data provider cannot return valid data."""


@dataclass(frozen=True)
class HttpClient:
    """Minimal GET-only client for public/no-key provider endpoints."""

    timeout_seconds: float = 10.0

    def get_json(self, url: str) -> Any:
        # Authentication headers are deliberately not accepted here. Current
        # market-data adapters use public endpoints and only need a user agent.
        request = Request(url, headers={"User-Agent": "Trading-System-V3.0/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise ProviderError(f"GET failed: {url}") from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise ProviderError(f"Invalid numeric value: {value!r}") from exc
