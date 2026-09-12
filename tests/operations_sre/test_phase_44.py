from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.operations_sre.metrics import RequestMetrics
from app.operations_sre.preflight import main, production_preflight
from interfaces.api.config import FastApiSettings
from interfaces.api.fastapi_app import create_fastapi_app
from interfaces.api.service import TradingApiService


def production_env(tmp_path: Path) -> dict[str, str]:
    data = tmp_path / "data"
    backup = tmp_path / "backup"
    data.mkdir()
    backup.mkdir()
    universe = tmp_path / "universe.json"
    universe.write_text("{}", encoding="utf-8")
    return {
        "TRADING_API_ENV": "production",
        "TRADING_API_KEY": "a9-strong-key-material-7f31",
        "TRADING_API_ALLOWED_HOSTS": "api.example.com",
        "TRADING_TLS_TERMINATED": "1",
        "TRADING_DB_PATH": str(data / "trading.db"),
        "TRADING_UNIVERSE_PATH": str(universe),
        "TRADING_BACKUP_PATH": str(backup),
    }


def test_production_preflight_passes_explicit_durable_layout(tmp_path: Path) -> None:
    report = production_preflight(production_env(tmp_path))
    assert report.ready
    assert "tls_termination" in report.checks
    assert "separate_backup_target" in report.checks


def test_preflight_cli_uses_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in production_env(tmp_path).items():
        monkeypatch.setenv(key, value)
    main()
    assert "Production infrastructure preflight: PASS" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("TRADING_TLS_TERMINATED", "0"),
        ("TRADING_API_KEY", "changeme"),
        ("TRADING_DB_PATH", "relative.db"),
    ],
)
def test_preflight_fails_closed(tmp_path: Path, field: str, value: str) -> None:
    env = production_env(tmp_path)
    env[field] = value
    with pytest.raises(ValueError):
        production_preflight(env)


def test_metrics_are_low_cardinality_and_thread_safe() -> None:
    metrics = RequestMetrics()
    first = metrics.begin()
    metrics.finish("GET", 200, first)
    second = metrics.begin()
    metrics.finish("DELETE", 503, second)
    output = metrics.render_prometheus()
    assert 'method="GET",status_class="2xx"} 1' in output
    assert 'method="OTHER",status_class="5xx"} 1' in output
    assert "trading_api_http_requests_in_flight 0" in output
    assert "path=" not in output


def test_production_security_headers_and_protected_metrics() -> None:
    settings = FastApiSettings(
        environment="production",
        require_api_key=True,
        api_key="a9-strong-key-material-7f31",
        allowed_hosts=("api.example.com",),
    )
    app = create_fastapi_app(TradingApiService(), settings=settings)
    with TestClient(app, base_url="https://api.example.com") as client:
        denied = client.get("/metrics")
        allowed = client.get("/metrics", headers={"X-API-Key": settings.api_key or ""})
        health = client.get("/healthz")
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert "trading_api_http_requests_total" in allowed.text
    assert health.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    assert health.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_metrics_endpoint_can_be_disabled() -> None:
    app = create_fastapi_app(
        TradingApiService(), settings=FastApiSettings(metrics_enabled=False)
    )
    with TestClient(app) as client:
        assert client.get("/metrics").status_code == 404
