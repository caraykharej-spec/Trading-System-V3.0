from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HealthResponse:
    status: str
    mode: str
    version: str

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "mode": self.mode, "version": self.version}


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: dict[str, Any]

    @classmethod
    def ok(cls, body: dict[str, Any]) -> "ApiResponse":
        return cls(200, body)

    @classmethod
    def bad_request(cls, code: str, message: str) -> "ApiResponse":
        return cls(400, {"error": ApiError(code, message).to_dict()})

    @classmethod
    def not_found(cls, code: str, message: str) -> "ApiResponse":
        return cls(404, {"error": ApiError(code, message).to_dict()})

    @classmethod
    def conflict(cls, code: str, message: str) -> "ApiResponse":
        return cls(409, {"error": ApiError(code, message).to_dict()})

    @classmethod
    def server_error(cls, code: str, message: str) -> "ApiResponse":
        return cls(500, {"error": ApiError(code, message).to_dict()})
