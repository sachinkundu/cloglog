"""T-312: pin the absence of `import yaml` at the 4 scalar-key sites.

Each entry below was previously a `python3 -c 'import yaml'` block. The
T-312 fix replaces them with a shared stdlib-only helper. Phase 0b
(T-313) handles the remaining nested-mapping site at
plugins/cloglog/hooks/protect-worktree-writes.sh — that file is
intentionally NOT in this pin set.

If a future edit reintroduces `import yaml` at any of these sites, the
hook will silently break on hosts whose system python3 lacks PyYAML —
exactly the failure mode docs/invariants.md:76 captures.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SCALAR_HOOK_FILES = [
    REPO_ROOT / "plugins/cloglog/hooks/worktree-create.sh",
    REPO_ROOT / "plugins/cloglog/hooks/quality-gate.sh",
    REPO_ROOT / "plugins/cloglog/hooks/enforce-task-transitions.sh",
]

LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing"
    return p.read_text(encoding="utf-8")


def test_scalar_hooks_have_no_import_yaml() -> None:
    for path in SCALAR_HOOK_FILES:
        body = _read(path)
        assert "import yaml" not in body, (
            f"{path.relative_to(REPO_ROOT)} reintroduced `import yaml` — "
            "use plugins/cloglog/hooks/lib/parse-yaml-scalar.sh instead. "
            "See docs/invariants.md:76."
        )


def test_scalar_hooks_source_the_shared_helper() -> None:
    """Positive pin: each hook must source the helper, not just remove yaml."""
    for path in SCALAR_HOOK_FILES:
        body = _read(path)
        assert "lib/parse-yaml-scalar.sh" in body, (
            f"{path.relative_to(REPO_ROOT)} must source the shared helper "
            "(plugins/cloglog/hooks/lib/parse-yaml-scalar.sh). "
            "Inline grep+sed drift is what T-312 closed."
        )
        assert "read_yaml_scalar " in body, (
            f"{path.relative_to(REPO_ROOT)} sources the helper but never "
            "calls read_yaml_scalar — dead source line."
        )


def test_launch_skill_template_emits_no_import_yaml() -> None:
    """The launch.sh template inside SKILL.md must not bake in import yaml.

    The template is rendered into a standalone bash exec inside the
    worktree (see Step 4c), with no plugin root in scope. We allow an
    inlined grep+sed equivalent — but `import yaml` is forbidden, since
    the rendered script runs under whatever python3 the host happens to
    have.
    """
    body = _read(LAUNCH_SKILL)
    # Extract the launch.sh heredoc body (between "<< EOF" and the closing EOF).
    match = re.search(
        r'cat > "\$\{WORKTREE_PATH\}/\.cloglog/launch\.sh" << EOF\n(.*?)\nEOF',
        body,
        flags=re.DOTALL,
    )
    assert match, (
        "Could not find the `cat > ... launch.sh << EOF` heredoc in the "
        "launch SKILL.md — has the template been restructured?"
    )
    template = match.group(1)
    assert "import yaml" not in template, (
        "The launch.sh template still bakes `import yaml` into the "
        "rendered launcher — T-312 forbids this. Inline a grep+sed "
        "equivalent that mirrors plugins/cloglog/hooks/lib/parse-yaml-scalar.sh."
    )


def test_launch_skill_template_uses_grep_sed_for_backend_url() -> None:
    """Pin the rendered _backend_url() shape: grep + sed scalar parse."""
    body = _read(LAUNCH_SKILL)
    match = re.search(
        r'cat > "\$\{WORKTREE_PATH\}/\.cloglog/launch\.sh" << EOF\n(.*?)\nEOF',
        body,
        flags=re.DOTALL,
    )
    assert match
    template = match.group(1)
    # Locate the _backend_url() function block.
    fn = re.search(r"_backend_url\(\)\s*\{(.*?)\n\}", template, flags=re.DOTALL)
    assert fn, "_backend_url() function missing from launch.sh template"
    body_fn = fn.group(1)
    assert "grep '^backend_url:'" in body_fn, (
        "_backend_url() must use the documented grep+sed scalar shape — "
        "matches plugins/cloglog/hooks/lib/parse-yaml-scalar.sh"
    )
    assert "sed 's/^backend_url:[[:space:]]*//'" in body_fn


def test_helper_simulates_missing_pyyaml_for_each_hook(tmp_path: Path) -> None:
    """Cross-cut: each hook's helper-sourced parse must work in a stripped env.

    We copy the helper + a minimal config, then source the helper exactly
    as each hook does (resolving `lib/parse-yaml-scalar.sh` from the hook's
    own directory) and assert the read succeeds with no python in PATH.

    This catches a regression where a hook is edited to drop the
    `source` line or to use the wrong relative path.
    """
    import subprocess
    import textwrap

    helper = REPO_ROOT / "plugins/cloglog/hooks/lib/parse-yaml-scalar.sh"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "backend_url: http://stripped-env:8000\nquality_command: make ci\nproject_id: x-1\n"
    )

    # Replicate the resolution pattern each hook uses: HOOK_DIR via BASH_SOURCE,
    # then `source "${HOOK_DIR}/lib/parse-yaml-scalar.sh"`. We simulate this
    # by placing a tiny shim at <tmp>/hook.sh that mirrors that prologue.
    hook_dir = tmp_path / "hooks"
    lib_dir = hook_dir / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "parse-yaml-scalar.sh").write_text(helper.read_text(encoding="utf-8"))

    shim = hook_dir / "shim.sh"
    shim.write_text(
        textwrap.dedent("""\
        #!/bin/bash
        HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        # shellcheck source=lib/parse-yaml-scalar.sh
        source "${HOOK_DIR}/lib/parse-yaml-scalar.sh"
        read_yaml_scalar "$1" "$2" "$3"
    """)
    )

    # Run with PATH stripped of project python and no PYTHONPATH — proves the
    # helper does not depend on `python3` being importable as `yaml`.
    out = subprocess.run(
        [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "PYTHONPATH=/dev/null",
            "bash",
            str(shim),
            str(cfg),
            "backend_url",
            "http://default:8000",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.rstrip("\n") == "http://stripped-env:8000"

    out = subprocess.run(
        [
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "PYTHONPATH=/dev/null",
            "bash",
            str(shim),
            str(cfg),
            "quality_command",
            "make quality",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.rstrip("\n") == "make ci"
