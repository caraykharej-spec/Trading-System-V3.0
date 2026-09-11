from __future__ import annotations

from threading import get_ident

import pytest
from fastapi.testclient import TestClient

from app.deployment_runtime.auth_validation_layer import RateLimitFoundation
from interfaces.api.config import FastApiSettings
from interfaces.api.fastapi_app import (
    ApiRuntime,
    create_fastapi_app,
    create_fastapi_runtime_app,
)
from interfaces.api.service import TradingApiService


def test_versioned_health_and_openapi_are_available() -> None:
    app = create_fastapi_app(TradingApiService())
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        probe = client.get("/healthz")
        assert probe.status_code == 200

        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        paths = schema.json()["paths"]
        assert "/api/v1/assistant/query" in paths
        assert "/api/v1/runtime/cycle" in paths


def test_positions_delegate_to_existing_service_contract() -> None:
    service = TradingApiService(positions_provider=lambda: [{"symbol": "BTC/USDT"}])
    app = create_fastapi_app(service)
    with TestClient(app) as client:
        response = client.get("/api/v1/positions")
    assert response.status_code == 200
    assert response.json() == {"positions": [{"symbol": "BTC/USDT"}]}


def test_validation_errors_use_structured_400_contract() -> None:
    app = create_fastapi_app(TradingApiService())
    with TestClient(app) as client:
        response = client.get("/api/v1/opportunities?limit=0")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_api_key_policy_is_fail_closed_and_documented() -> None:
    settings = FastApiSettings(
        require_api_key=True,
        api_key="1234567890abcdef",
    )
    app = create_fastapi_app(TradingApiService(), settings=settings)
    with TestClient(app) as client:
        missing = client.get("/api/v1/positions")
        invalid = client.get("/api/v1/positions", headers={"X-API-Key": "wrong-key"})
        valid = client.get(
            "/api/v1/positions",
            headers={"X-API-Key": "1234567890abcdef"},
        )
        schema = client.get("/openapi.json").json()

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200
    schemes = schema["components"]["securitySchemes"].values()
    assert any(item.get("name") == "X-API-Key" for item in schemes)


def test_runtime_cycle_is_disabled_by_default() -> None:
    service = TradingApiService(cycle_runner=lambda: {"status": "ok"})
    app = create_fastapi_app(service)
    with TestClient(app) as client:
        response = client.post("/api/v1/runtime/cycle")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RUNTIME_ACTION_DISABLED"


def test_runtime_cycle_requires_explicit_auth_when_enabled() -> None:
    settings = FastApiSettings(
        require_api_key=True,
        api_key="1234567890abcdef",
        runtime_cycle_enabled=True,
    )
    service = TradingApiService(cycle_runner=lambda: {"status": "ok"})
    app = create_fastapi_app(service, settings=settings)
    with TestClient(app) as client:
        unauthorized = client.post("/api/v1/runtime/cycle")
        authorized = client.post(
            "/api/v1/runtime/cycle",
            headers={"X-API-Key": "1234567890abcdef"},
        )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json() == {"cycle": {"status": "ok"}}


def test_rate_limit_returns_429_and_retry_after() -> None:
    settings = FastApiSettings(rate_limit_requests=2, rate_limit_window_seconds=60)
    app = create_fastapi_app(TradingApiService(), settings=settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        limited = client.get("/api/v1/health")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 0


def test_payload_limit_rejects_large_json_before_route_execution() -> None:
    settings = FastApiSettings(max_body_bytes=1024)
    app = create_fastapi_app(TradingApiService(), settings=settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/assistant/query",
            json={"query": "x" * 1500},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_request_id_and_security_headers_are_present() -> None:
    app = create_fastapi_app(TradingApiService())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health",
            headers={"X-Request-ID": "phase41-test"},
        )
    assert response.headers["X-Request-ID"] == "phase41-test"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_production_settings_require_key_and_explicit_hosts() -> None:
    with pytest.raises(ValueError):
        FastApiSettings.from_env({"TRADING_API_ENV": "production"})

    settings = FastApiSettings.from_env(
        {
            "TRADING_API_ENV": "production",
            "TRADING_API_KEY": "1234567890abcdef",
            "TRADING_API_ALLOWED_HOSTS": "api.example.com",
        }
    )
    assert settings.require_api_key is True
    assert settings.docs_enabled is False
    assert settings.allowed_hosts == ("api.example.com",)


def test_runtime_policy_rejects_public_state_mutation() -> None:
    with pytest.raises(ValueError):
        FastApiSettings(runtime_cycle_enabled=True)


def test_fixed_window_limiter_resets_after_window() -> None:
    current = [0.0]
    limiter = RateLimitFoundation(
        max_requests=2,
        window_seconds=10,
        clock=lambda: current[0],
    )
    assert limiter.check("client") is True
    assert limiter.check("client") is True
    assert limiter.check("client") is False
    current[0] = 11.0
    assert limiter.check("client") is True


def test_runtime_and_service_calls_share_one_serial_worker_thread() -> None:
    created_on: list[int] = []
    called_on: list[int] = []
    closed_on: list[int] = []

    def runtime_factory() -> ApiRuntime:
        created_on.append(get_ident())
        service = TradingApiService(
            positions_provider=lambda: called_on.append(get_ident()) or []
        )
        return ApiRuntime(
            service=service,
            close=lambda: closed_on.append(get_ident()),
        )

    app = create_fastapi_runtime_app(runtime_factory)
    with TestClient(app) as client:
        assert client.get("/api/v1/positions").status_code == 200

    assert created_on
    assert created_on == called_on == closed_on
