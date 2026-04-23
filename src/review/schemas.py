"""Pydantic DTOs for the Review context.

Kept deliberately small — one read DTO for the dashboard badge surface. The
Gateway sequencer consumes ``ReviewTurnSnapshot`` (from ``interfaces.py``) for
control flow; ``schemas.py`` is only for HTTP response shapes if/when a
dashboard endpoint is added.
"""

from __future__ import annotations

from pydantic import BaseModel


class ReviewTurnResponse(BaseModel):
    """Public shape of a single persisted turn, for dashboard surface."""

    pr_url: str
    head_sha: str
    stage: str
    turn_number: int
    status: str
    finding_count: int | None = None
    consensus_reached: bool
    elapsed_seconds: float | None = None
