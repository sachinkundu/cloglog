"""FastAPI application factory.

Composes routes from all bounded contexts into a single app.
"""

import asyncio
import contextlib
import hmac
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from src.gateway.notification_listener import run_notification_listener

    task = asyncio.create_task(run_notification_listener())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_app() -> FastAPI:
    app = FastAPI(
        title="cloglog",
        description="Multi-project Kanban dashboard for managing autonomous AI coding agents",
        version="0.1.0",
        lifespan=lifespan,
    )

    class ApiAccessControlMiddleware(BaseHTTPMiddleware):
        """Enforce credential-based access control on all API routes.

        Every API request must present one of these valid credentials:

        1. MCP request (Authorization: Bearer <key> + X-MCP-Request) — allowed everywhere.
           The middleware passes these through; specific routes use CurrentMcpService
           to validate the service key when needed.
        2. Agent token or project API key (Authorization: Bearer <key>) — only /agents/* routes.
           Validated downstream by CurrentAgent or CurrentProject dependencies.
        3. Dashboard key (X-Dashboard-Key) — allowed on non-agent routes.

        Agents cannot access board/document routes directly — they must go through MCP.
        """

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            from src.shared.config import settings

            path = request.url.path

            # Only gate /api/v1/ routes; health checks etc. pass through
            if not path.startswith("/api/v1/"):
                return await call_next(request)

            auth = request.headers.get("Authorization")
            mcp = request.headers.get("X-MCP-Request")
            dashboard_key = (
                request.headers.get("X-Dashboard-Key")
                or request.query_params.get("dashboard_key")  # SSE/EventSource fallback
            )
            is_agent_route = path.startswith("/api/v1/agents/")

            # Path 1: MCP server (Authorization + X-MCP-Request) — allowed everywhere.
            # Routes that need MCP service key validation use CurrentMcpService dependency.
            if auth and mcp:
                return await call_next(request)

            # Path 2: Bearer token only — restricted to agent routes
            # (validated downstream by CurrentAgent or CurrentProject)
            if auth and not mcp:
                if is_agent_route:
                    return await call_next(request)
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Agents can only access /api/v1/agents/* routes. "
                            "Use MCP tools for all board operations."
                        )
                    },
                )

            # Path 3: Dashboard key — allowed on non-agent routes
            if dashboard_key:
                if not hmac.compare_digest(dashboard_key, settings.dashboard_secret):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Invalid dashboard key"},
                    )
                return await call_next(request)

            # No credentials at all — reject
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Authentication required. "
                        "Provide Authorization, X-MCP-Request, or X-Dashboard-Key header."
                    )
                },
            )

    app.add_middleware(ApiAccessControlMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Context routes
    from src.board.routes import router as board_router
    from src.gateway.routes import router as gateway_router
    from src.gateway.sse import router as sse_router

    app.include_router(board_router, prefix="/api/v1")
    app.include_router(gateway_router, prefix="/api/v1")
    app.include_router(sse_router, prefix="/api/v1")

    from src.agent.routes import router as agent_router

    app.include_router(agent_router, prefix="/api/v1")

    from src.document.routes import router as document_router

    app.include_router(document_router, prefix="/api/v1")

    return app
