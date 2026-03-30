"""L1: static demo UI + reverse proxy to L2 (P5)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from inspectio.v3.settings import V3L1Settings

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_FORWARD_HEADERS = ("content-type", "idempotency-key", "x-trace-id")


def _pick_headers(request: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _FORWARD_HEADERS:
        if key in request.headers:
            out[key] = request.headers[key]
    return out


async def _proxy_to_l2(request: Request, l2_path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.l2
    body = await request.body()
    upstream = await client.request(
        request.method,
        l2_path,
        content=body if body else None,
        headers=_pick_headers(request),
        params=request.query_params,
    )
    media_type = upstream.headers.get("content-type")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=media_type,
    )


def _register_proxy_routes(app: FastAPI) -> None:
    @app.post("/messages")
    async def proxy_messages(request: Request) -> Response:
        return await _proxy_to_l2(request, "/messages")

    @app.post("/messages/repeat")
    async def proxy_repeat(request: Request) -> Response:
        return await _proxy_to_l2(request, "/messages/repeat")

    @app.get("/messages/success")
    async def proxy_success(request: Request) -> Response:
        return await _proxy_to_l2(request, "/messages/success")

    @app.get("/messages/failed")
    async def proxy_failed(request: Request) -> Response:
        return await _proxy_to_l2(request, "/messages/failed")

    @app.get("/healthz")
    async def proxy_healthz(request: Request) -> Response:
        return await _proxy_to_l2(request, "/healthz")


def create_l1_app(*, l2_client: httpx.AsyncClient | None = None) -> FastAPI:
    """Inject ``l2_client`` in tests (state set immediately; no lifespan)."""

    if l2_client is not None:
        app = FastAPI(title="Inspectio L1", version="0.0.0")
        app.state.l2 = l2_client
        _register_proxy_routes(app)
        app.mount(
            "/",
            StaticFiles(directory=str(_STATIC_DIR), html=True),
            name="static",
        )
        return app

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = V3L1Settings()
        base = settings.l2_base_url.rstrip("/")
        timeout = httpx.Timeout(settings.l2_http_timeout_sec)
        limits = httpx.Limits(
            max_connections=settings.l2_max_connections,
            max_keepalive_connections=min(256, settings.l2_max_connections),
        )
        async with httpx.AsyncClient(
            base_url=base,
            timeout=timeout,
            limits=limits,
        ) as client:
            app.state.l2 = client
            yield

    app = FastAPI(title="Inspectio L1", version="0.0.0", lifespan=lifespan)
    _register_proxy_routes(app)
    app.mount(
        "/",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )
    return app
