from __future__ import annotations

from dataclasses import dataclass, field
from os import environ
from typing import Mapping


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _parse_int(value: str | None, *, default: int, name: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _parse_float(value: str | None, *, default: float, name: str) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _parse_csv(value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items


@dataclass(frozen=True)
class FastApiSettings:
    """Fail-closed transport/runtime policy for the production FastAPI adapter."""

    environment: str = "development"
    title: str = "Trading System V3 API"
    api_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    docs_enabled: bool = True
    require_api_key: bool = False
    api_key: str | None = field(default=None, repr=False)
    api_key_header: str = "X-API-Key"
    request_id_header: str = "X-Request-ID"
    rate_limit_requests: int = 120
    rate_limit_window_seconds: float = 60.0
    max_body_bytes: int = 16_384
    runtime_cycle_enabled: bool = False
    allowed_hosts: tuple[str, ...] = ("*",)
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        environment = self.environment.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test, or production")
        object.__setattr__(self, "environment", environment)

        if not self.api_prefix.startswith("/") or self.api_prefix == "/":
            raise ValueError("api_prefix must be a non-root absolute path")
        if self.api_prefix.endswith("/"):
            raise ValueError("api_prefix must not end with a slash")
        if not self.api_key_header.strip() or not self.request_id_header.strip():
            raise ValueError("API header names must not be empty")
        if self.rate_limit_requests < 1:
            raise ValueError("rate_limit_requests must be positive")
        if self.rate_limit_window_seconds <= 0:
            raise ValueError("rate_limit_window_seconds must be positive")
        if self.max_body_bytes < 1024:
            raise ValueError("max_body_bytes must be at least 1024")
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must contain at least one host")
        if self.api_key is not None and len(self.api_key) < 16:
            raise ValueError("api_key must contain at least 16 characters")
        if self.require_api_key and self.api_key is None:
            raise ValueError("require_api_key needs TRADING_API_KEY")
        if self.runtime_cycle_enabled and not self.require_api_key:
            raise ValueError("runtime cycle can only be enabled when API-key auth is required")
        if environment == "production":
            if not self.require_api_key or self.api_key is None:
                raise ValueError("production API requires API-key authentication")
            if "*" in self.allowed_hosts:
                raise ValueError("production API requires an explicit host allowlist")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "FastApiSettings":
        source = environ if env is None else env
        environment = source.get("TRADING_API_ENV", "development").strip().lower()
        production = environment == "production"
        require_key = _parse_bool(
            source.get("TRADING_API_REQUIRE_KEY"), default=production
        )
        docs_enabled = _parse_bool(
            source.get("TRADING_API_DOCS_ENABLED"), default=not production
        )
        default_hosts = () if production else ("*",)
        return cls(
            environment=environment,
            title=source.get("TRADING_API_TITLE", "Trading System V3 API"),
            api_version=source.get("TRADING_API_VERSION", "1.0.0"),
            api_prefix=source.get("TRADING_API_PREFIX", "/api/v1"),
            docs_enabled=docs_enabled,
            require_api_key=require_key,
            api_key=source.get("TRADING_API_KEY"),
            api_key_header=source.get("TRADING_API_KEY_HEADER", "X-API-Key"),
            request_id_header=source.get("TRADING_API_REQUEST_ID_HEADER", "X-Request-ID"),
            rate_limit_requests=_parse_int(
                source.get("TRADING_API_RATE_LIMIT_REQUESTS"),
                default=120,
                name="TRADING_API_RATE_LIMIT_REQUESTS",
            ),
            rate_limit_window_seconds=_parse_float(
                source.get("TRADING_API_RATE_LIMIT_WINDOW_SECONDS"),
                default=60.0,
                name="TRADING_API_RATE_LIMIT_WINDOW_SECONDS",
            ),
            max_body_bytes=_parse_int(
                source.get("TRADING_API_MAX_BODY_BYTES"),
                default=16_384,
                name="TRADING_API_MAX_BODY_BYTES",
            ),
            runtime_cycle_enabled=_parse_bool(
                source.get("TRADING_API_RUNTIME_CYCLE_ENABLED"), default=False
            ),
            allowed_hosts=_parse_csv(
                source.get("TRADING_API_ALLOWED_HOSTS"), default=default_hosts
            ),
            cors_origins=_parse_csv(
                source.get("TRADING_API_CORS_ORIGINS"), default=()
            ),
        )
