"""Background task for heartbeat timeout cleanup."""

from __future__ import annotations

import asyncio
import logging

from src.agent.repository import AgentRepository
from src.agent.services import AgentService
from src.board.repository import BoardRepository
from src.shared.database import async_session_factory

logger = logging.getLogger(__name__)


async def run_heartbeat_checker(interval_seconds: int = 60) -> None:
    """Periodically check for timed-out agent sessions.

    Runs as an asyncio background task in the FastAPI lifespan.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with async_session_factory() as session:
                repo = AgentRepository(session)
                board_repo = BoardRepository(session)
                service = AgentService(repo, board_repo)
                timed_out = await service.check_heartbeat_timeouts()
                if timed_out:
                    logger.info(
                        "Cleaned up %d timed-out agent(s): %s",
                        len(timed_out),
                        timed_out,
                    )
        except Exception:
            logger.exception("Error checking heartbeat timeouts")
