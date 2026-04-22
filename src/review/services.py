"""Review services — high-level orchestration around ``IReviewTurnRegistry``.

Kept deliberately thin. The turn-accounting business rules live here so that
the Gateway sequencer composes them rather than re-implementing each check.
"""

from __future__ import annotations

from src.review.interfaces import IReviewTurnRegistry


class ReviewTurnService:
    """Facade over ``IReviewTurnRegistry`` used by the Gateway sequencer."""

    def __init__(self, registry: IReviewTurnRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> IReviewTurnRegistry:
        return self._registry
