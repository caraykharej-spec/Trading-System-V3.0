from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

from interfaces.api.http import create_server
from interfaces.api.service import TradingApiService


def _request(server, method: str, path: str) -> tuple[int, dict]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port, timeout=2)
        connection.request(method, path)
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, body
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_health_endpoint() -> None:
    server = create_server("127.0.0.1", 0, lambda: TradingApiService())
    status, body = _request(server, "GET", "/health")
    assert status == 200
    assert body["status"] == "ok"


def test_unknown_endpoint_returns_404() -> None:
    server = create_server("127.0.0.1", 0, lambda: TradingApiService())
    status, body = _request(server, "GET", "/missing")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_invalid_opportunity_limit_returns_400() -> None:
    server = create_server("127.0.0.1", 0, lambda: TradingApiService())
    status, body = _request(server, "GET", "/opportunities?limit=nope")
    assert status == 400
    assert body["error"]["code"] == "INVALID_LIMIT"


def test_performance_endpoint_uses_configured_provider() -> None:
    server = create_server(
        "127.0.0.1",
        0,
        lambda: TradingApiService(analytics_provider=lambda: {"total_trades": 4}),
    )
    status, body = _request(server, "GET", "/analytics/performance")
    assert status == 200
    assert body == {"performance": {"total_trades": 4}}


def test_cycle_endpoint_is_post_only() -> None:
    server = create_server(
        "127.0.0.1",
        0,
        lambda: TradingApiService(cycle_runner=lambda: {"ok": True}),
    )
    status, body = _request(server, "GET", "/runtime/cycle")
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"

    server = create_server(
        "127.0.0.1",
        0,
        lambda: TradingApiService(cycle_runner=lambda: {"ok": True}),
    )
    status, body = _request(server, "POST", "/runtime/cycle")
    assert status == 200
    assert body == {"cycle": {"ok": True}}
