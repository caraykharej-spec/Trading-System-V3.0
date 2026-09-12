from fastapi.testclient import TestClient

from interfaces.api.config import FastApiSettings
from interfaces.api.fastapi_app import create_fastapi_app
from interfaces.api.service import TradingApiService


def test_dashboard_and_packaged_assets_are_served_same_origin() -> None:
    app = create_fastapi_app(TradingApiService())
    with TestClient(app) as client:
        page = client.get("/dashboard")
        css = client.get("/dashboard/assets/styles.css")
        js = client.get("/dashboard/assets/app.js")

    assert page.status_code == 200
    assert "Professional Dashboard" in page.text
    assert css.status_code == 200
    assert ".app-shell" in css.text
    assert js.status_code == 200
    assert 'const API_ROOT = "/api/v1"' in js.text
    assert page.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]


def test_dashboard_can_be_disabled_without_changing_api_routes() -> None:
    settings = FastApiSettings(dashboard_enabled=False)
    app = create_fastapi_app(TradingApiService(), settings=settings)
    with TestClient(app) as client:
        dashboard = client.get("/dashboard")
        health = client.get("/api/v1/health")

    assert dashboard.status_code == 404
    assert health.status_code == 200


def test_dashboard_setting_can_be_loaded_from_environment() -> None:
    settings = FastApiSettings.from_env({"TRADING_API_DASHBOARD_ENABLED": "0"})
    assert settings.dashboard_enabled is False
