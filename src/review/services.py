"""Review services — high-level orchestration around ``IReviewTurnRegistry``.

``make_review_turn_registry`` is the **Open Host Service** boundary used by the
Gateway sequencer. Gateway imports ``src.review.services``; it does NOT import
``src.review.repository``. If the Review context ever swaps to a different
backing store, that change is internal — Gateway's contract is the
``IReviewTurnRegistry`` Protocol plus this factory. See
``docs/ddd-context-map.md`` (Gateway → Review = Open Host Service) and the
PR #187 round 2 CRITICAL that moved us off the direct repository import.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.review.interfaces import IReviewTurnRegistry


def make_review_turn_registry(session: AsyncSession) -> IReviewTurnRegistry:
    """Build an ``IReviewTurnRegistry`` bound to an open async session.

    Kept as a free function so callers never see the concrete
    ``ReviewTurnRepository`` type — the return annotation is the Protocol.
    The concrete import lives inside the function body so ``services`` can
    be imported without loading SQLAlchemy column definitions.
    """
    from src.review.repository import ReviewTurnRepository

    return ReviewTurnRepository(session)


class ReviewTurnService:
    """Facade over ``IReviewTurnRegistry`` used by the Gateway sequencer."""

    def __init__(self, registry: IReviewTurnRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> IReviewTurnRegistry:
        return self._registry
