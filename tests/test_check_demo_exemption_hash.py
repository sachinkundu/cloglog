"""Pin test for the silent-failure invariant:

> When a branch ships a ``docs/demos/<branch>/exemption.md`` instead of
> a ``demo.md``, ``scripts/check-demo.sh`` MUST hash the current
> ``git diff origin/main...HEAD`` and refuse the exemption if the
> stored ``diff_hash`` does not match. A mismatch means the agent
> classified an older diff and then kept coding — the exemption no
> longer covers what is being shipped.

The rule lives in ``docs/invariants.md`` § Demo gate — exemption diff-hash.

Failure modes this pins:
1. Frontmatter parser that picks up a ``diff_hash:`` line outside the
   YAML fence (e.g., the reasoning body mentions the word) and silently
   accepts a stale exemption.
2. Hash computation that diverges from the classifier's convention
   (``git diff origin/main...HEAD``) — two-dot vs three-dot, staged vs
   committed, different diff flags — any of which would produce
   ``"valid exemption"`` on every commit because the stored hash can
   never match the recomputed one, OR the reverse, where any stored
   hash matches by accident.
3. Missing ``diff_hash`` in frontmatter silently treated as match.

The test fabricates a temp git repo, creates a code change, stores the
correct hash in an ``exemption.md`` frontmatter, and asserts exit 0.
Then it dirties the diff and asserts the same file now produces exit
1 with the ``exemption is stale`` message. Finally it asserts a
missing ``diff_hash`` field is rejected distinctly.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_DEMO_SH = REPO_ROOT / "scripts" / "check-demo.sh"


def _run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _init_repo(tmp_path: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_DIR": str(tmp_path / ".git"),
        "GIT_WORK_TREE": str(tmp_path),
    }
    _run(["git", "init", "-b", "main", "."], tmp_path, env).check_returncode()
    env.pop("GIT_DIR")
    env.pop("GIT_WORK_TREE")
    (tmp_path / "README.md").write_text("# test\n")
    _run(["git", "add", "README.md"], tmp_path, env).check_returncode()
    _run(["git", "commit", "-m", "initial"], tmp_path, env).check_returncode()
    head = _run(["git", "rev-parse", "HEAD"], tmp_path, env).stdout.strip()
    _run(["git", "update-ref", "refs/remotes/origin/main", head], tmp_path, env).check_returncode()
    _run(["git", "checkout", "-b", "feature-branch"], tmp_path, env).check_returncode()
    return env


def _commit_code_change(repo: Path, env: dict[str, str]) -> None:
    """Add a non-allowlisted file so the gate proceeds past the allowlist
    short-circuit and reaches the demo-or-exemption check."""
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "gateway.py").write_text("def handler():\n    return 1\n")
    _run(["git", "add", "src/gateway.py"], repo, env).check_returncode()
    _run(["git", "commit", "-m", "add handler"], repo, env).check_returncode()


def _current_diff_hash(repo: Path, env: dict[str, str]) -> str:
    """Mirror check-demo.sh: ``sha256sum`` of
    ``git diff $MERGE_BASE HEAD -- . ':(exclude)docs/demos/'`` where
    MERGE_BASE is the origin/main merge-base. The pathspec exclude is
    load-bearing — without it, committing exemption.md would change
    the diff bytes and invalidate its own pin."""
    merge_base = _run(
        ["git", "merge-base", "origin/main", "HEAD"],
        repo,
        env,
    ).stdout.strip()
    diff = subprocess.check_output(
        ["git", "diff", merge_base, "HEAD", "--", ".", ":(exclude)docs/demos/"],
        cwd=repo,
        env=env,
        text=True,
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def _write_exemption(
    repo: Path,
    diff_hash: str,
    include_hash: bool = True,
) -> Path:
    demo_dir = repo / "docs" / "demos" / "feature-branch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    exemption = demo_dir / "exemption.md"
    hash_line = f"diff_hash: {diff_hash}\n" if include_hash else ""
    exemption.write_text(
        f"""---
verdict: no_demo
{hash_line}classifier: demo-classifier
generated_at: 2026-04-24T12:00:00Z
---

## Why no demo

Pure internal refactor. No user-observable behaviour change.

Incidental text that mentions diff_hash: should_not_be_picked_up.

## Changed files

src/gateway.py
"""
    )
    return exemption


def test_exemption_with_matching_hash_passes(tmp_path: Path) -> None:
    """Real-flow happy path — commit the code change, write the
    exemption with the correct hash, commit the exemption too, then
    run the gate. The exemption.md commit MUST NOT invalidate its own
    hash (pathspec-exclude of docs/demos/ keeps the hash pinned to the
    code the classifier evaluated)."""
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    _write_exemption(tmp_path, _current_diff_hash(tmp_path, env))
    # Commit the exemption — real agents do this; an untracked
    # exemption.md would never be the state the gate sees at push time.
    _run(
        ["git", "add", "docs/demos/feature-branch/exemption.md"],
        tmp_path,
        env,
    ).check_returncode()
    _run(
        ["git", "commit", "-m", "add exemption"],
        tmp_path,
        env,
    ).check_returncode()
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode == 0, (
        f"exemption with matching diff_hash was rejected after commit.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "Exemption verified" in result.stdout


def test_exemption_commit_does_not_invalidate_its_own_hash(tmp_path: Path) -> None:
    """Regression pin for the F-51 self-invalidation bug: once
    exemption.md is committed, ``git diff $MERGE_BASE HEAD`` now
    includes the exemption file itself. Without the pathspec exclude,
    its bytes would shift the hash and make every real-flow PR fail
    the gate on its first push. Assert explicitly that the hash
    computed BEFORE the exemption commit equals the hash computed
    AFTER — that equality is what makes the exemption path usable."""
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    hash_before_exemption = _current_diff_hash(tmp_path, env)
    _write_exemption(tmp_path, hash_before_exemption)
    _run(
        ["git", "add", "docs/demos/feature-branch/exemption.md"],
        tmp_path,
        env,
    ).check_returncode()
    _run(
        ["git", "commit", "-m", "add exemption"],
        tmp_path,
        env,
    ).check_returncode()
    hash_after_exemption = _current_diff_hash(tmp_path, env)
    assert hash_before_exemption == hash_after_exemption, (
        "Committing exemption.md shifted the diff_hash — the "
        "pathspec exclude of docs/demos/ is broken or missing.\n"
        f"before: {hash_before_exemption}\nafter:  {hash_after_exemption}"
    )


def test_exemption_with_stale_hash_rejected(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    # Write the exemption with the hash captured *now*, then add another
    # commit — the stored hash is now stale relative to HEAD.
    _write_exemption(tmp_path, _current_diff_hash(tmp_path, env))
    # Commit the exemption first, then dirty the diff.
    _run(["git", "add", "docs/demos/feature-branch/exemption.md"], tmp_path, env)
    _run(["git", "commit", "-m", "add exemption"], tmp_path, env).check_returncode()
    (tmp_path / "src" / "gateway.py").write_text(
        "def handler():\n    return 2  # drifted after exemption\n"
    )
    _run(["git", "add", "src/gateway.py"], tmp_path, env)
    _run(["git", "commit", "-m", "drift"], tmp_path, env).check_returncode()
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode != 0
    assert "exemption is stale" in result.stdout, (
        f"Expected 'exemption is stale' message on drift.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_exemption_missing_hash_rejected(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    _write_exemption(tmp_path, diff_hash="", include_hash=False)
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode != 0
    assert "missing a diff_hash" in result.stdout, (
        f"Expected rejection of exemption missing diff_hash.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_exemption_parser_ignores_hash_in_body(tmp_path: Path) -> None:
    """The prose body of an exemption may legitimately mention a hash
    value (e.g., classifier reasoning quoting a hash). The frontmatter
    parser must only read the first YAML fence."""
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    correct_hash = _current_diff_hash(tmp_path, env)
    demo_dir = tmp_path / "docs" / "demos" / "feature-branch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    # Frontmatter has the correct hash. Body contains a DIFFERENT
    # ``diff_hash:`` line AT COLUMN 0 (worst case for a naive
    # ``grep '^diff_hash:'`` parser) — after the closing ``---`` fence,
    # so the fence-counting logic in awk is what saves us. If the
    # parser picks up the body value the recomputed hash will mismatch.
    bad_hash = "0" * 64
    (demo_dir / "exemption.md").write_text(
        f"""---
verdict: no_demo
diff_hash: {correct_hash}
classifier: demo-classifier
generated_at: 2026-04-24T12:00:00Z
---

## Why no demo

Pure refactor.

A previous classification round computed a different hash; audit log:
diff_hash: {bad_hash}
(the authoritative hash is in the frontmatter above; this body line
exists to catch parsers that don't respect the YAML fence.)
"""
    )
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode == 0, (
        "Parser picked up a body-level diff_hash instead of the frontmatter one.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_demo_md_wins_over_exemption(tmp_path: Path) -> None:
    """If both artifacts exist, demo.md takes precedence. The spec is
    explicit: ``If both demo.md and exemption.md exist, demo.md wins.``"""
    env = _init_repo(tmp_path)
    _commit_code_change(tmp_path, env)
    demo_dir = tmp_path / "docs" / "demos" / "feature-branch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    # A minimal demo.md — the script's showboat branch will print
    # "skipping verification" if showboat is not available, which is the
    # likely case in the test environment. Either way the gate passes.
    (demo_dir / "demo.md").write_text("# demo\n\nStakeholder can X.\n")
    # Exemption with a DELIBERATELY WRONG hash — should not be consulted.
    _write_exemption(tmp_path, diff_hash="0" * 64)
    result = _run(["bash", str(CHECK_DEMO_SH)], tmp_path, env)
    assert result.returncode == 0, (
        "demo.md precedence failed — the gate consulted exemption.md "
        "even though demo.md is present.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "exemption is stale" not in result.stdout
