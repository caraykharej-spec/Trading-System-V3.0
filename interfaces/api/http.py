from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from interfaces.api.models import ApiResponse
from interfaces.api.service import TradingApiService


class TradingHttpHandler(BaseHTTPRequestHandler):
    """Minimal stdlib HTTP adapter; all business behavior stays in TradingApiService."""

    service_factory: Callable[[], TradingApiService] | None = None
    max_json_body_bytes: int = 16_384

    def _service(self) -> TradingApiService:
        if self.service_factory is None:
            raise RuntimeError("service_factory is not configured")
        return self.service_factory()

    def _write(self, response: ApiResponse) -> None:
        payload = json.dumps(response.body, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, object]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        length = int(raw_length)
        if length < 1 or length > self.max_json_body_bytes:
            raise ValueError("JSON body size is invalid")
        raw = self.rfile.read(length)
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("JSON body must be an object")
        return {str(key): value for key, value in decoded.items()}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            service = self._service()
            if parsed.path == "/health":
                self._write(service.health())
            elif parsed.path == "/ready":
                self._write(service.readiness())
            elif parsed.path == "/positions":
                self._write(service.positions())
            elif parsed.path == "/opportunities":
                values = parse_qs(parsed.query).get("limit", ["10"])
                try:
                    limit = int(values[0])
                except ValueError:
                    self._write(
                        ApiResponse.bad_request("INVALID_LIMIT", "limit must be an integer")
                    )
                    return
                self._write(service.opportunities(limit))
            elif parsed.path == "/analytics/performance":
                self._write(service.performance())
            elif parsed.path == "/assistant/brief":
                self._write(service.assistant_brief())
            elif parsed.path == "/assistant/opportunity":
                symbol = parse_qs(parsed.query).get("symbol", [""])[0]
                self._write(service.assistant_opportunity(symbol))
            elif parsed.path == "/assistant/metrics":
                self._write(service.assistant_metrics())
            else:
                self._write(ApiResponse.not_found("NOT_FOUND", "endpoint not found"))
        except Exception:
            self._write(ApiResponse.server_error("INTERNAL_ERROR", "request could not be completed"))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/assistant/query":
            try:
                payload = self._read_json_body()
                query = payload.get("query")
                session_id = payload.get("session_id")
                if not isinstance(query, str):
                    raise ValueError("query must be a string")
                if session_id is not None and not isinstance(session_id, str):
                    raise ValueError("session_id must be a string when provided")
                self._write(self._service().assistant_query(query, session_id))
            except (ValueError, UnicodeDecodeError):
                self._write(
                    ApiResponse.bad_request(
                        "INVALID_ASSISTANT_REQUEST",
                        "assistant request must contain a valid JSON query payload",
                    )
                )
            except Exception:
                self._write(
                    ApiResponse.server_error("INTERNAL_ERROR", "request could not be completed")
                )
            return

        if path != "/runtime/cycle":
            self._write(ApiResponse.not_found("NOT_FOUND", "endpoint not found"))
            return
        try:
            self._write(self._service().run_cycle())
        except Exception:
            self._write(ApiResponse.server_error("INTERNAL_ERROR", "request could not be completed"))

    def log_message(self, format: str, *args: object) -> None:
        return


def create_server(
    host: str,
    port: int,
    service_factory: Callable[[], TradingApiService],
) -> ThreadingHTTPServer:
    if not host:
        raise ValueError("host must not be empty")
    if port < 0 or port > 65535:
        raise ValueError("port must be between 0 and 65535")
    handler = type(
        "ConfiguredTradingHttpHandler",
        (TradingHttpHandler,),
        {"service_factory": staticmethod(service_factory)},
    )
    return ThreadingHTTPServer((host, port), handler)
