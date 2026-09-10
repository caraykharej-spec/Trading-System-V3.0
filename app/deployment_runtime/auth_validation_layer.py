"""Authentication and request validation foundation for API security."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class APIKey:
    key: str
    name: str
    permissions: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    created_at: datetime = field(default_factory=datetime.utcnow)


class AuthenticationManager:
    def __init__(self):
        self.keys: Dict[str, APIKey] = {}

    def register_key(self, api_key: APIKey):
        self.keys[api_key.key] = api_key

    def validate_key(self, key: str) -> bool:
        item = self.keys.get(key)
        return bool(item and item.enabled)


class RequestValidator:
    def validate(self, request: Dict) -> ValidationResult:
        if not request:
            return ValidationResult(False, "Empty request")
        return ValidationResult(True, "Request validated")


class RateLimitFoundation:
    def __init__(self):
        self.requests = {}

    def check(self, identity: str) -> bool:
        return True
