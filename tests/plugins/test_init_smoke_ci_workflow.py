"""Pin test: T-324.

The fresh-repo init smoke (T-319/T-321/T-323 pin tests) must run as a CI
job on every PR so plugin portability regressions block merge. The smoke
job lives at `.github/workflows/init-smoke.yml`. These pins guard against
two regression modes:

1. The smoke workflow file disappears or stops invoking the two pin
   test files.
2. The workflow grows a `paths:` filter that excludes plugin/skill/doc
   changes, silently letting portability regressions slip through.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOKE_WORKFLOW = REPO_ROOT / ".github/workflows/init-smoke.yml"
MAIN_CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"


def _read_workflow() -> str:
    assert SMOKE_WORKFLOW.exists(), (
        f"{SMOKE_WORKFLOW} missing — the init smoke job is the CI gate "
        "that blocks plugin portability regressions on fresh-repo init. "
        "Restore the workflow file."
    )
    return SMOKE_WORKFLOW.read_text(encoding="utf-8")


def test_workflow_runs_init_on_fresh_repo_pin() -> None:
    body = _read_workflow()
    assert "tests/plugins/test_init_on_fresh_repo.py" in body, (
        "init-smoke.yml must invoke tests/plugins/test_init_on_fresh_repo.py "
        "(T-319/T-321 placeholder + scope-template pins)."
    )


def test_workflow_runs_plugin_no_cloglog_citations_pin() -> None:
    body = _read_workflow()
    assert "tests/plugins/test_plugin_no_cloglog_citations.py" in body, (
        "init-smoke.yml must invoke tests/plugins/test_plugin_no_cloglog_citations.py "
        "(T-323 host-literal sweep)."
    )


def test_workflow_runs_skills_no_remote_set_url_pin() -> None:
    body = _read_workflow()
    assert "tests/plugins/test_skills_no_remote_set_url.py" in body, (
        "init-smoke.yml must invoke tests/plugins/test_skills_no_remote_set_url.py "
        "(T-363 inline-URL push pin). ci.yml's `paths:` filter excludes "
        "`plugins/**` and `CLAUDE.md`, so this every-PR gate is the only "
        "always-on enforcement that catches a SKILL-only edit reintroducing "
        "the persistent-bot-token `git remote set-url origin` antipattern."
    )


def test_workflow_runs_launch_and_template_pins() -> None:
    """T-368: the launch SKILL and AGENT_PROMPT.md template pins guard
    workflow-templating invariants (env propagation across `/clear`,
    quoted-heredoc launch.sh rendering, agent_started liveness
    deadline, and worktree-vs-project-root inbox path direction). All
    four are SKILL/template-only edits, so a regression on any of them
    would slip past `ci.yml`'s `paths:` filter that excludes
    `plugins/**`. The init-smoke job is the only always-on gate.
    """
    body = _read_workflow()
    for path in (
        "tests/plugins/test_launch_skill_exports_gh_app_env.py",
        "tests/plugins/test_launch_skill_renders_clean_launch_sh.py",
        "tests/plugins/test_launch_skill_has_agent_started_timeout.py",
        "tests/plugins/test_agent_prompt_template_correct_inbox_paths.py",
    ):
        assert path in body, (
            f"init-smoke.yml must invoke {path} — workflow-templating "
            "regressions only fire on operator machines (no production "
            "code path) and ci.yml's `paths:` filter does not cover "
            "plugins/**."
        )


def test_workflow_triggers_on_pull_request() -> None:
    body = _read_workflow()
    assert re.search(r"^on:\s*$", body, re.MULTILINE), (
        "init-smoke.yml must declare an `on:` trigger block."
    )
    assert "pull_request:" in body, (
        "init-smoke.yml must trigger on `pull_request` so the smoke "
        "runs against every PR before merge."
    )


def test_main_ci_runs_on_init_smoke_workflow_changes() -> None:
    """Cross-coverage pin: `ci.yml` must list `init-smoke.yml` in its
    `pull_request.paths:` filter so that the PR-creation surface
    (`opened`/`reopened`/`ready_for_review` — see T-377) still triggers
    the main suite when the smoke workflow itself is being edited.

    Note: post-T-377 ``ci.yml`` no longer fires on ``synchronize``, so
    the always-on per-push catch for self-disabling workflow edits has
    moved to ``init-smoke.yml`` itself (which runs the workflow YAML
    pin tests on every PR push from the PR branch). This `paths:`
    pin still matters for the very first PR push.
    """
    assert MAIN_CI_WORKFLOW.exists(), f"{MAIN_CI_WORKFLOW} missing"
    body = MAIN_CI_WORKFLOW.read_text(encoding="utf-8")
    assert ".github/workflows/init-smoke.yml" in body, (
        "ci.yml's `pull_request.paths:` list must include "
        "`.github/workflows/init-smoke.yml` so the first PR push (PR-creation "
        "events) re-runs the workflow YAML pins."
    )


def test_init_smoke_runs_workflow_yaml_pins() -> None:
    """T-377 cross-coverage pin: with ci.yml no longer triggered on
    `pull_request: synchronize`, the post-T-377 CI runs come from
    `repository_dispatch: codex-finalized` and execute ci.yml from the
    DEFAULT branch — not the PR head. That means a self-disabling edit
    to ci.yml on a PR would never run its own pin tests against the
    modified workflow. ``init-smoke.yml`` is the always-on per-push
    PR-branch gate, so the workflow YAML pin tests must live here.
    Without this pin, a future revert of ``init-smoke.yml`` could quietly
    drop the workflow YAML coverage and a broken ci.yml could ship.
    """
    body = _read_workflow()
    for path in (
        "tests/plugins/test_init_smoke_ci_workflow.py",
        "tests/plugins/test_ci_workflow_codex_finalized_trigger.py",
    ):
        assert path in body, (
            f"init-smoke.yml must invoke {path} — repository_dispatch CI "
            "runs ci.yml from the default branch, so workflow YAML pins "
            "MUST execute on the PR branch via init-smoke for self-"
            "disabling-workflow-edit coverage. See "
            "docs/design/ci-codex-trigger.md."
        )


def test_workflow_has_no_paths_filter() -> None:
    """The smoke must run on every PR — a `paths:` filter would silently
    skip portability checks on PRs that don't happen to touch the
    filtered globs (e.g. plugin/, docs/), which is exactly the surface
    we're guarding."""
    body = _read_workflow()
    # Allow `paths-ignore` only if explicitly empty; flag any `paths:` key.
    for line in body.splitlines():
        stripped = line.strip()
        assert not re.match(r"^paths\s*:", stripped), (
            "init-smoke.yml must NOT use a `paths:` filter — it must run on "
            "every PR. A paths filter would skip portability checks for PRs "
            "that don't match the globs, defeating the gate."
        )
