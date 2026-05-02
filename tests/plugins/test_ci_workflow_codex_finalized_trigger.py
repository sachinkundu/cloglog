"""T-377 pin: ci.yml fires only on codex finalization or PR-creation surface.

The default ``pull_request`` trigger fires on ``opened``, ``synchronize``,
and ``reopened``. Codex iterates by pushing patches (each = synchronize),
so the unrestricted default re-runs CI on every intermediate state — what
T-377 set out to stop.

These pins guard against re-introducing ``synchronize`` or dropping the
``codex-finalized`` dispatch trigger via an inattentive workflow edit.

Cross-coverage: ``init-smoke.yml`` keeps its default
``pull_request`` trigger (every push) — pinned in
``test_init_smoke_ci_workflow.py``. The two workflows are deliberately
decoupled so a portability regression cannot wait on codex.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"


def _load_workflow() -> dict:
    assert CI_WORKFLOW.exists(), f"{CI_WORKFLOW} missing"
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


# PyYAML translates the literal ``on:`` key into Python ``True`` because
# YAML 1.1 treats ``on`` as a boolean. Both forms are accepted here so the
# pin stays robust if the workflow file later moves to ``"on":`` (string).
def _on_block(workflow: dict) -> dict:
    return workflow.get(True) or workflow.get("on") or {}


class TestPullRequestTriggerNarrowed:
    def test_pull_request_types_explicitly_listed(self) -> None:
        on = _on_block(_load_workflow())
        pr = on.get("pull_request") or {}
        types = pr.get("types")
        assert types is not None, (
            "ci.yml's `pull_request` trigger must declare an explicit `types:` list — "
            "an absent list defaults to [opened, synchronize, reopened] which "
            "re-runs CI on every codex iteration push (T-377)."
        )

    def test_synchronize_is_not_in_pull_request_types(self) -> None:
        on = _on_block(_load_workflow())
        pr = on.get("pull_request") or {}
        types = pr.get("types") or []
        assert "synchronize" not in types, (
            "ci.yml must NOT trigger on `pull_request: synchronize` — that re-runs "
            "CI on every push, defeating T-377's codex-finalization gate. "
            "Use `repository_dispatch: codex-finalized` instead, fired by "
            "src/gateway/review_loop.py once stage B is terminal."
        )

    def test_pr_creation_surface_present(self) -> None:
        """At least the `opened` trigger must remain — without it a brand-new PR
        would have no CI signal until codex first finalizes (which can take
        minutes-to-hours), masking obviously-broken PRs from human reviewers."""
        on = _on_block(_load_workflow())
        types = (on.get("pull_request") or {}).get("types") or []
        assert "opened" in types, (
            "ci.yml must trigger on `pull_request: opened` — first-push CI is the "
            "fastest signal a human reviewer has on a brand-new PR."
        )


class TestRepositoryDispatchTrigger:
    def test_repository_dispatch_codex_finalized_present(self) -> None:
        on = _on_block(_load_workflow())
        rd = on.get("repository_dispatch") or {}
        types = rd.get("types") or []
        assert "codex-finalized" in types, (
            "ci.yml must declare `repository_dispatch: types: [codex-finalized]` "
            "— this is how the review server (src/gateway/review_loop.py) tells "
            "Actions to run CI once stage B reaches consensus or burns through "
            "codex_max_turns. Without it, post-creation pushes never trigger CI."
        )


class TestCheckoutPinsHeadSha:
    def test_checkout_uses_client_payload_head_sha(self) -> None:
        """The default ``actions/checkout`` ref for ``repository_dispatch`` is
        the default branch's HEAD — running CI against ``main`` instead of
        the PR. Both jobs (``ci`` and ``e2e-browser``) must explicitly opt
        into ``client_payload.head_sha`` so the workflow tests the SHA the
        reviewer signed off on."""
        body = CI_WORKFLOW.read_text(encoding="utf-8")
        # Two checkouts; both must reference client_payload.head_sha.
        head_sha_refs = re.findall(r"client_payload\.head_sha", body)
        assert len(head_sha_refs) >= 2, (
            f"Expected ≥2 references to `client_payload.head_sha` in ci.yml "
            f"(one per `actions/checkout` invocation); found {len(head_sha_refs)}. "
            "Without it, repository_dispatch runs would test the default branch HEAD."
        )

    def test_mirror_step_creates_check_run_on_head_sha(self) -> None:
        """When triggered by repository_dispatch, the workflow run's
        auto-attached check_runs land on the default branch SHA — not the
        PR's head_sha. Auto-merge-gate consults `gh pr checks` (head_sha-
        scoped), so we mirror the job result onto head_sha via the Checks
        API. Pin guards against the mirror step being silently dropped."""
        body = CI_WORKFLOW.read_text(encoding="utf-8")
        assert "check-runs" in body, (
            "ci.yml must POST a check_run on `client_payload.head_sha` when "
            "triggered by repository_dispatch — otherwise CI failures are "
            "invisible to the auto-merge gate. See "
            "docs/design/ci-codex-trigger.md."
        )
        assert "github.event_name == 'repository_dispatch'" in body, (
            "The check_run mirror step must be guarded by "
            "`github.event_name == 'repository_dispatch'` so pull_request "
            "runs (which already attach checks to head_sha automatically) "
            "do not double-post."
        )
