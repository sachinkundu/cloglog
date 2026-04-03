"""FastAPI application factory.

Composes routes from all bounded contexts into a single app.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="cloglog",
        description="Multi-project Kanban dashboard for managing autonomous AI coding agents",
        version="0.1.0",
    )

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

    app.include_router(board_router, prefix="/api/v1")
    # app.include_router(agent_router, prefix="/api/v1")
    # app.include_router(document_router, prefix="/api/v1")

    return app
