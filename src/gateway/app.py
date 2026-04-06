"""FastAPI application factory.

Composes routes from all bounded contexts into a single app.
"""

import asyncio
import contextlib
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

    class AgentRouteIsolationMiddleware(BaseHTTPMiddleware):
        """Block direct agent API calls to non-agent routes.

        Requests with an Authorization header (API key) are blocked from
        non-agent routes UNLESS they include the X-MCP-Request header,
        which identifies them as coming from the MCP server (the sanctioned
        path for board operations).

        - Agent direct call (API key only) → blocked from board routes
        - MCP server call (API key + X-MCP-Request) → allowed everywhere
        - Frontend UI (no API key) → allowed everywhere
        """

        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            auth = request.headers.get("Authorization")
            mcp = request.headers.get("X-MCP-Request")
            path = request.url.path
            if (
                auth
                and not mcp
                and path.startswith("/api/v1/")
                and not path.startswith("/api/v1/agents/")
            ):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Agents can only access /api/v1/agents/* routes. "
                            "Use MCP tools for all board operations."
                        )
                    },
                )
            return await call_next(request)

    app.add_middleware(AgentRouteIsolationMiddleware)

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
