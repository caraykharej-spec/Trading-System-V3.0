from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.deployment_runtime.auth_validation_layer import (
    APIKey,
    AuthenticationManager,
    RateLimitFoundation,
)
from app.operations_sre.metrics import RequestMetrics
from interfaces.api.config import FastApiSettings
from interfaces.api.models import ApiResponse
from interfaces.api.schemas import AssistantQueryRequest, ErrorEnvelope, HealthSchema
from interfaces.api.service import TradingApiService
from interfaces.dashboard import dashboard_static_dir


RuntimeFactory = Callable[[], "ApiRuntime"]
ServiceOperation = Callable[[TradingApiService], ApiResponse]


@dataclass
class ApiRuntime:
    """Service and owned resource cleanup executed on one serialized worker."""

    service: TradingApiService
    close: Callable[[], None] | None = None


class ApiPlatformError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _request_id(raw: str | None) -> str:
    if raw is not None and _REQUEST_ID_PATTERN.fullmatch(raw):
        return raw
    return uuid4().hex


def _json_response(response: ApiResponse) -> JSONResponse:
    return JSONResponse(status_code=response.status_code, content=response.body)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return _json_response(ApiResponse(status_code, {"error": {"code": code, "message": message}}))


class PlatformMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: object,
        *,
        settings: FastApiSettings,
        limiter: RateLimitFoundation,
        metrics: RequestMetrics,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings
        self._limiter = limiter
        self._metrics = metrics

    def _identity(self, request: Request) -> str:
        api_key = request.headers.get(self._settings.api_key_header)
        if api_key:
            return "key:" + sha256(api_key.encode("utf-8")).hexdigest()
        if request.client is not None:
            return f"client:{request.client.host}"
        return "anonymous"

    def _apply_headers(self, response: Response, request_id: str) -> Response:
        response.headers[self._settings.request_id_header] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if self._settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self' http: https:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = _request_id(request.headers.get(self._settings.request_id_header))
        request.state.request_id = request_id
        metric_started = self._metrics.begin()
        if request.url.path.startswith(self._settings.api_prefix):
            if request.method in {"POST", "PUT", "PATCH"}:
                raw_length = request.headers.get("content-length")
                if raw_length is not None:
                    try:
                        length = int(raw_length)
                    except ValueError:
                        response = _error_response(
                            400,
                            "INVALID_CONTENT_LENGTH",
                            "Content-Length must be an integer",
                        )
                        secured = self._apply_headers(response, request_id)
                        self._metrics.finish(request.method, secured.status_code, metric_started)
                        return secured
                    if length < 0:
                        response = _error_response(
                            400,
                            "INVALID_CONTENT_LENGTH",
                            "Content-Length must not be negative",
                        )
                        secured = self._apply_headers(response, request_id)
                        self._metrics.finish(request.method, secured.status_code, metric_started)
                        return secured
                    if length > self._settings.max_body_bytes:
                        response = _error_response(
                            413,
                            "PAYLOAD_TOO_LARGE",
                            "request body exceeds the configured API limit",
                        )
                        secured = self._apply_headers(response, request_id)
                        self._metrics.finish(request.method, secured.status_code, metric_started)
                        return secured

            identity = self._identity(request)
            if not self._limiter.check(identity):
                response = _error_response(
                    429,
                    "RATE_LIMITED",
                    "request rate limit exceeded",
                )
                response.headers["Retry-After"] = str(self._limiter.retry_after(identity))
                secured = self._apply_headers(response, request_id)
                self._metrics.finish(request.method, secured.status_code, metric_started)
                return secured

        try:
            downstream_response = await call_next(request)
        except Exception:
            self._metrics.finish(request.method, 500, metric_started)
            raise
        secured = self._apply_headers(downstream_response, request_id)
        self._metrics.finish(request.method, secured.status_code, metric_started)
        return secured


_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope},
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    409: {"model": ErrorEnvelope},
    413: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
    500: {"model": ErrorEnvelope},
}


async def _invoke(request: Request, operation: ServiceOperation) -> JSONResponse:
    runtime = cast(ApiRuntime, request.app.state.api_runtime)
    executor = cast(ThreadPoolExecutor, request.app.state.api_executor)
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(executor, operation, runtime.service)
    return _json_response(response)


def _install_openapi_security(app: FastAPI, settings: FastApiSettings) -> None:
    """Document dynamic API-key auth without coupling runtime auth to annotations."""

    if not settings.require_api_key:
        return

    public_paths = {
        f"{settings.api_prefix}/health",
        f"{settings.api_prefix}/ready",
    }

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes["ApiKeyAuth"] = {
            "type": "apiKey",
            "in": "header",
            "name": settings.api_key_header,
        }

        paths = schema.get("paths", {})
        for path, path_item in paths.items():
            if path in public_paths or not path.startswith(settings.api_prefix):
                continue
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method.lower() not in {
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "options",
                    "head",
                    "trace",
                }:
                    continue
                if isinstance(operation, dict):
                    operation["security"] = [{"ApiKeyAuth": []}]

        app.openapi_schema = schema
        return schema

    setattr(app, "openapi", custom_openapi)


def create_fastapi_runtime_app(
    runtime_factory: RuntimeFactory,
    *,
    settings: FastApiSettings | None = None,
) -> FastAPI:
    """Build the production ASGI adapter around the existing TradingApiService.

    The application/runtime is created and all service operations are executed on
    the same single worker thread. This keeps the current SQLite connection model
    thread-affine while preventing blocking provider calls from stalling the ASGI
    event loop.
    """

    effective = settings or FastApiSettings.from_env()
    limiter = RateLimitFoundation(
        max_requests=effective.rate_limit_requests,
        window_seconds=effective.rate_limit_window_seconds,
    )
    metrics = RequestMetrics()
    authentication = AuthenticationManager()
    if effective.api_key is not None:
        authentication.register_key(
            APIKey(key=effective.api_key, name="fastapi-platform", permissions=["api"])
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="trading-api")
        runtime: ApiRuntime | None = None
        try:
            loop = asyncio.get_running_loop()
            runtime = await loop.run_in_executor(executor, runtime_factory)
            app.state.api_runtime = runtime
            app.state.api_executor = executor
            yield
        finally:
            if runtime is not None and runtime.close is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(executor, runtime.close)
            executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(
        title=effective.title,
        version=effective.api_version,
        docs_url="/docs" if effective.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if effective.docs_enabled else None,
        lifespan=lifespan,
    )

    if effective.allowed_hosts != ("*",):
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(effective.allowed_hosts))
    if effective.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(effective.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=[
                "Content-Type",
                effective.api_key_header,
                effective.request_id_header,
            ],
        )
    app.add_middleware(
        PlatformMiddleware,
        settings=effective,
        limiter=limiter,
        metrics=metrics,
    )
    app.state.sre_metrics = metrics

    if effective.dashboard_enabled:
        static_dir = dashboard_static_dir()
        app.mount(
            "/dashboard/assets",
            StaticFiles(directory=str(static_dir)),
            name="dashboard-assets",
        )

        @app.get("/dashboard", include_in_schema=False)
        @app.get("/dashboard/", include_in_schema=False)
        async def dashboard() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    def require_access(request: Request) -> None:
        if not effective.require_api_key:
            return
        api_key = request.headers.get(effective.api_key_header)
        if api_key is None or not authentication.validate_key(api_key):
            raise ApiPlatformError(
                401,
                "UNAUTHORIZED",
                f"a valid {effective.api_key_header} header is required",
            )

    @app.exception_handler(ApiPlatformError)
    async def platform_error_handler(
        request: Request,
        exc: ApiPlatformError,
    ) -> JSONResponse:
        del request
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request, exc
        return _error_response(
            400,
            "VALIDATION_ERROR",
            "request path, query parameters, or body failed validation",
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return _error_response(
            500,
            "INTERNAL_ERROR",
            "request could not be completed",
        )

    public = APIRouter(prefix=effective.api_prefix, responses=_ERROR_RESPONSES)
    protected = APIRouter(
        prefix=effective.api_prefix,
        dependencies=[Depends(require_access)],
        responses=_ERROR_RESPONSES,
    )

    @app.get("/healthz", include_in_schema=False)
    async def health_probe(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.health())

    @app.get("/readyz", include_in_schema=False)
    async def readiness_probe(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.readiness())

    if effective.metrics_enabled:
        @app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_access)])
        async def metrics_endpoint() -> Response:
            return Response(metrics.render_prometheus(), media_type="text/plain; version=0.0.4")

    @public.get("/health", response_model=HealthSchema, tags=["system"])
    async def health(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.health())

    @public.get("/ready", tags=["system"])
    async def readiness(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.readiness())

    @protected.get("/positions", tags=["trading-state"])
    async def positions(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.positions())

    @protected.get("/opportunities", tags=["opportunities"])
    async def opportunities(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> JSONResponse:
        return await _invoke(request, lambda service: service.opportunities(limit))

    @protected.get("/analytics/performance", tags=["analytics"])
    async def performance(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.performance())

    @protected.get("/market-data/universe-coverage", tags=["market-data"])
    async def universe_coverage(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.universe_coverage())

    @protected.get("/assistant/brief", tags=["assistant"])
    async def assistant_brief(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.assistant_brief())

    @protected.get("/assistant/opportunity", tags=["assistant"])
    async def assistant_opportunity(
        request: Request,
        symbol: Annotated[str, Query(min_length=1, max_length=64)],
    ) -> JSONResponse:
        return await _invoke(
            request,
            lambda service: service.assistant_opportunity(symbol),
        )

    @protected.get("/assistant/metrics", tags=["assistant"])
    async def assistant_metrics(request: Request) -> JSONResponse:
        return await _invoke(request, lambda service: service.assistant_metrics())

    @protected.post("/assistant/query", tags=["assistant"])
    async def assistant_query(
        request: Request,
        payload: AssistantQueryRequest,
    ) -> JSONResponse:
        return await _invoke(
            request,
            lambda service: service.assistant_query(payload.query, payload.session_id),
        )

    @protected.post("/runtime/cycle", tags=["runtime"])
    async def runtime_cycle(request: Request) -> JSONResponse:
        if not effective.runtime_cycle_enabled:
            return _error_response(
                403,
                "RUNTIME_ACTION_DISABLED",
                "runtime cycle API action is disabled by policy",
            )
        return await _invoke(request, lambda service: service.run_cycle())

    app.include_router(public)
    app.include_router(protected)
    _install_openapi_security(app, effective)
    return app


def create_fastapi_app(
    service: TradingApiService,
    *,
    settings: FastApiSettings | None = None,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    """Convenience adapter for a pre-built service, primarily tests/embedding."""

    return create_fastapi_runtime_app(
        lambda: ApiRuntime(service=service, close=shutdown_callback),
        settings=settings,
    )
