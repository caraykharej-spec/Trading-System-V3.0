"""Authentication and request validation foundation for API security."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class APIKey:
    key: str
    name: str
    permissions: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class AuthenticationManager:
    def __init__(self) -> None:
        self.keys: dict[str, APIKey] = {}

    def register_key(self, api_key: APIKey) -> None:
        self.keys[api_key.key] = api_key

    def validate_key(self, key: str) -> bool:
        item = self.keys.get(key)
        return bool(item and item.enabled)


class RequestValidator:
    def validate(self, request: dict[str, object]) -> ValidationResult:
        if not request:
            return ValidationResult(False, "Empty request")
        return ValidationResult(True, "Request validated")


class RateLimitFoundation:
    def __init__(self) -> None:
        self.requests: dict[str, int] = {}

    def check(self, identity: str) -> bool:
        return True
