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

    def test_ireviewer_turn_registry_exposes_codex_status_by_pr(self) -> None:
        """IReviewTurnRegistry must expose codex_status_by_pr (T-409).

        The method is the Open Host Service contract Board calls to derive
        discriminated codex status per PR. If this test fails, the interface
        was removed or renamed — update the Board route accordingly.
        """
        import inspect

        from src.review.interfaces import IReviewTurnRegistry

        assert hasattr(IReviewTurnRegistry, "codex_status_by_pr"), (
            "IReviewTurnRegistry.codex_status_by_pr is missing — "
            "Board.get_board calls it for the discriminated codex badge (T-409)."
        )
        sig = inspect.signature(IReviewTurnRegistry.codex_status_by_pr)
        params = set(sig.parameters.keys())
        assert "project_id" in params, "codex_status_by_pr must accept project_id"
        assert "pr_url_to_head_sha" in params, "codex_status_by_pr must accept pr_url_to_head_sha"
        assert "max_turns" in params, "codex_status_by_pr must accept max_turns"
        assert "max_pr_sessions" in params, (
            "codex_status_by_pr must accept max_pr_sessions (T-424) — gates "
            "EXHAUSTED on the PR-wide ``MAX_REVIEWS_PER_PR`` cap rather than "
            "the per-session ``codex_max_turns``."
        )

    def test_codex_status_enum_exported_from_interfaces(self) -> None:
        """CodexStatus must be importable from src.review.interfaces (not models)."""
        from src.review.interfaces import CodexStatus

        assert CodexStatus.NOT_STARTED.value == "not_started"
        assert CodexStatus.STALE.value == "stale"
        assert CodexStatus.PASS.value == "pass"
