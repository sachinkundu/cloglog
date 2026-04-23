"""DDD priority-3 guard: Board must not import Review internals.

T-260 adds a boolean projection (``codex_review_picked_up``) from the Review
context onto ``TaskCard``. Board sources it via the Open Host Service
factory ``src.review.services.make_review_turn_registry`` whose return type
is the ``IReviewTurnRegistry`` Protocol. Board must NEVER import
``src.review.models`` or ``src.review.repository`` — direct or lazy —
otherwise the cross-context dependency is back and the projection starts
leaking SQLAlchemy rows into Board's call graph.

Mirrors ``tests/gateway/test_review_engine_t248.py::TestGatewayReviewContextBoundary``
for the Board → Review edge.
"""

from __future__ import annotations

import pathlib


class TestBoardReviewContextBoundary:
    def test_board_does_not_import_review_repository(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "board"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text()
            if "from src.review.repository" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
            if "import src.review.repository" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
        assert offenders == [], (
            "Board modules must not import src.review.repository directly "
            f"(use src.review.services instead). Offenders: {offenders}"
        )

    def test_board_does_not_import_review_models(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "board"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text()
            if "from src.review.models" in text or "import src.review.models" in text:
                offenders.append(str(path.relative_to(root.parent.parent)))
        assert offenders == [], (
            f"Board modules must not import src.review.models directly. Offenders: {offenders}"
        )
