from __future__ import annotations

from decimal import Decimal, InvalidOperation
from os import environ
from pathlib import Path
from typing import Mapping

from fastapi import FastAPI
import uvicorn

from app.application.composition import build_paper_application
from interfaces.api.config import FastApiSettings
from interfaces.api.fastapi_app import ApiRuntime, create_fastapi_runtime_app


def _parse_port(value: str | None) -> int:
    raw = value or "8000"
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError("TRADING_API_PORT must be an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("TRADING_API_PORT must be between 1 and 65535")
    return port


def _parse_initial_equity(value: str | None) -> Decimal:
    raw = value or "10000"
    try:
        equity = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("TRADING_INITIAL_EQUITY must be numeric") from exc
    if equity <= 0:
        raise ValueError("TRADING_INITIAL_EQUITY must be positive")
    return equity


def create_application(env: Mapping[str, str] | None = None) -> FastAPI:
    """ASGI factory for uvicorn/gunicorn-style process managers.

    The PAPER composition root is intentionally built inside the serialized API
    worker thread by the FastAPI lifespan. Importing this module does not open a
    database connection or perform provider network I/O.
    """

    source = environ if env is None else env
    settings = FastApiSettings.from_env(source)
    db_path = Path(source.get("TRADING_DB_PATH", "data/trading_system_v3.db"))
    universe_path = Path(source.get("TRADING_UNIVERSE_PATH", "config/universe.json"))
    initial_equity = _parse_initial_equity(source.get("TRADING_INITIAL_EQUITY"))

    def runtime_factory() -> ApiRuntime:
        application = build_paper_application(
            db_path=db_path,
            universe_path=universe_path,
            initial_equity=initial_equity,
        )
        return ApiRuntime(service=application.api, close=application.close)

    return create_fastapi_runtime_app(runtime_factory, settings=settings)


def main() -> None:
    """Run the single-process production FastAPI host.

    Horizontal scaling is intentionally deferred while the active composition
    uses process-local rate limiting and a single SQLite-backed application state.
    """

    host = environ.get("TRADING_API_HOST", "127.0.0.1")
    if not host.strip():
        raise ValueError("TRADING_API_HOST must not be empty")
    port = _parse_port(environ.get("TRADING_API_PORT"))
    log_level = environ.get("TRADING_API_LOG_LEVEL", "info").lower()
    if log_level not in {"critical", "error", "warning", "info", "debug", "trace"}:
        raise ValueError("TRADING_API_LOG_LEVEL is invalid")

    uvicorn.run(
        create_application(),
        host=host,
        port=port,
        log_level=log_level,
        proxy_headers=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
