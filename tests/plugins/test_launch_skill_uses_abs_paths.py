"""Backstop: T-284.

The launch skill's step 4c used to invoke ``.cloglog/on-worktree-create.sh``
via a relative path, silently assuming the caller had already ``cd``'d into
the new worktree. The Bash tool's shell persists ``cwd`` between calls, so
once a main agent ran ``cd <worktree>`` to satisfy the relative test, every
subsequent main-agent command inherited the worktree as ``cwd`` — ``git
status`` / ``git branch`` / ``Read`` / ``Write`` all drifted to the worktree's
tree, looking like cross-contamination of main.

The fix is to drive the snippet by absolute paths anchored on
``${WORKTREE_PATH}`` so the snippet is correct regardless of ``cwd`` and
the next reader who peels it out as a single Bash call doesn't need to
``cd`` to make it work.

These assertions pin the absolute-path discipline by *absence* — the only
form that survives is the ``${WORKTREE_PATH}/.cloglog/on-worktree-create.sh``
prefix. CLAUDE.md "Leak-after-fix" guidance: assert absence, not presence.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — fix the path or the file was moved"
    return p.read_text(encoding="utf-8")


def test_launch_skill_4c_uses_absolute_on_worktree_create_path() -> None:
    """The snippet must invoke the script via ``${WORKTREE_PATH}/.cloglog/...``.

    A regression that re-introduces a bare ``.cloglog/on-worktree-create.sh``
    invocation (no ``${WORKTREE_PATH}`` prefix, no leading ``/``) reopens
    the cwd-drift trap.
    """
    body = _read(LAUNCH_SKILL)
    assert '"${WORKTREE_PATH}/.cloglog/on-worktree-create.sh"' in body, (
        "Step 4c must invoke on-worktree-create.sh via the absolute "
        '"${WORKTREE_PATH}/.cloglog/on-worktree-create.sh" path so the '
        "snippet is safe to peel out as a single Bash call."
    )


def test_launch_skill_4c_has_no_relative_invocation_or_cd() -> None:
    """Assert *absence* of the relative invocation and of ``cd`` inside the
    Step 4c bash snippet.

    Bare prose mentions of ``.cloglog/on-worktree-create.sh`` (naming the
    file) are fine — the trap is when it is **invoked** as a command from
    a relative path, or when the snippet ``cd``s into the worktree to
    make a relative path resolve. We pin the bash code block under
    ``### 4c`` specifically.
    """
    body = _read(LAUNCH_SKILL)

    # Extract the bash code block immediately under "### 4c. ..."
    section_match = re.search(
        r"### 4c\..*?\n```bash\n(.*?)\n```",
        body,
        flags=re.DOTALL,
    )
    assert section_match, "Step 4c must contain a ```bash``` code block"
    snippet = section_match.group(1)

    # An invocation (as opposed to a prose mention) is the script path used
    # as a command. Forbid the bare-relative form: a `.cloglog/...` token
    # whose preceding character is neither `/` nor `}` (i.e. not part of an
    # absolute path or a `${WORKTREE_PATH}/` substitution).
    bad = re.findall(r"(?<![/}])\.cloglog/on-worktree-create\.sh", snippet)
    assert not bad, (
        "Step 4c snippet must invoke on-worktree-create.sh via the "
        "absolute ${WORKTREE_PATH}/.cloglog/on-worktree-create.sh path. "
        f"Found {len(bad)} relative reference(s) inside the bash block — "
        "this is the trap T-284 closed."
    )

    assert re.search(r"(^|[\s;&|])cd\s", snippet) is None, (
        "Step 4c snippet must not `cd` into the new worktree — the Bash "
        "tool's shell persists cwd across calls and a main agent would "
        "carry the worktree's cwd into every subsequent command. Pass "
        "WORKTREE_PATH as an env var and use the absolute script path."
    )


def test_launch_skill_backend_url_block_uses_grep_sed_not_yaml() -> None:
    """T-312: _backend_url() in the rendered launch.sh must use grep+sed.

    `python3 -c 'import yaml'` violates docs/invariants.md:76 — the system
    python3 launch.sh runs under typically lacks PyYAML, so the previous
    snippet silently swallowed ImportError and returned the default port,
    breaking unregister-by-path on portable hosts.
    """
    body = _read(LAUNCH_SKILL)
    fn_match = re.search(r"_backend_url\(\)\s*\{(.*?)\n\}", body, flags=re.DOTALL)
    assert fn_match, "_backend_url() block missing from launch SKILL.md"
    fn_body = fn_match.group(1)

    assert "import yaml" not in fn_body, (
        "_backend_url() must not embed `python3 -c 'import yaml'` — see "
        "docs/invariants.md:76 and plugins/cloglog/hooks/lib/parse-yaml-scalar.sh."
    )
    assert "grep '^backend_url:'" in fn_body, (
        "_backend_url() must read backend_url via the grep+sed shape that "
        "mirrors plugins/cloglog/hooks/lib/parse-yaml-scalar.sh."
    )


def test_launch_skill_4c_warns_against_cd_into_worktree() -> None:
    """The fix is structural; the prose must also state the discipline.

    A future edit that drops the warning lets the next reader rediscover
    the trap from first principles — and they will probably also `cd`
    before realising why the snippet uses absolute paths.
    """
    body = _read(LAUNCH_SKILL)
    assert "never `cd` into the new worktree" in body, (
        "Step 4c must explicitly warn against `cd`-ing into the new "
        "worktree from the main agent — the bash snippet alone doesn't "
        "explain *why* the absolute path matters."
    )


def test_launch_skill_documents_launch_sh_host_specificity() -> None:
    """T-317: launch.sh embeds operator-host absolute paths and must not be
    copied between operators or hosts.

    A future edit that removes this note leaves the next operator no
    explanation of why a launch.sh copied from a colleague's machine fails
    immediately — the gitignore does not communicate the constraint.
    """
    body = _read(LAUNCH_SKILL)
    assert "operator-host-specific" in body, (
        "Step 4e must state that launch.sh is operator-host-specific — "
        "the heredoc bakes absolute WORKTREE_PATH/PROJECT_ROOT paths at "
        "write time, so the file is invalid on any other machine."
    )
    assert "must not be copied between operators" in body or "Do not commit it" in body, (
        "Step 4e must explicitly warn that launch.sh must not be copied "
        "between operators or committed — gitignored does not mean portable."
    )
