from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderRole(str, Enum):
    LIVE_PRICE = "LIVE_PRICE"
    OHLCV_REST = "OHLCV_REST"
    OHLCV_STREAM = "OHLCV_STREAM"
    DISCOVERY = "DISCOVERY"


@dataclass(frozen=True)
class ProviderRegistration:
    name: str
    roles: frozenset[ProviderRole]
    public_no_key: bool
    transports: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("provider name cannot be empty")
        if not self.roles:
            raise ValueError("provider must expose at least one role")
        if not self.transports:
            raise ValueError("provider must expose at least one transport")


class MarketDataProviderRegistry:
    """Canonical registry of provider responsibilities and transport capabilities."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(self, registration: ProviderRegistration) -> None:
        key = registration.name.lower()
        if key in self._providers:
            raise ValueError(f"provider already registered: {registration.name}")
        self._providers[key] = registration

    def get(self, name: str) -> ProviderRegistration:
        registration = self._providers.get(name.lower())
        if registration is None:
            raise KeyError(name)
        return registration

    def for_role(self, role: ProviderRole) -> tuple[ProviderRegistration, ...]:
        return tuple(
            registration
            for registration in self._providers.values()
            if role in registration.roles
        )

    def all(self) -> tuple[ProviderRegistration, ...]:
        return tuple(self._providers.values())


def build_default_provider_registry() -> MarketDataProviderRegistry:
    registry = MarketDataProviderRegistry()
    registry.register(
        ProviderRegistration(
            name="storm",
            roles=frozenset({ProviderRole.LIVE_PRICE}),
            public_no_key=True,
            transports=("HTTPS",),
        )
    )
    registry.register(
        ProviderRegistration(
            name="gateio",
            roles=frozenset(
                {
                    ProviderRole.OHLCV_REST,
                    ProviderRole.OHLCV_STREAM,
                    ProviderRole.DISCOVERY,
                }
            ),
            public_no_key=True,
            transports=("HTTPS", "WSS"),
        )
    )
    registry.register(
        ProviderRegistration(
            name="yahoo",
            roles=frozenset({ProviderRole.OHLCV_REST}),
            public_no_key=True,
            transports=("HTTPS",),
        )
    )
    return registry
