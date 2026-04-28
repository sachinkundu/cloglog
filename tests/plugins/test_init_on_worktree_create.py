"""Pin tests: T-322.

init Step 4b's `on-worktree-create.sh` generation must:

1. Produce a non-empty script for every documented tech-stack matrix entry
   (Python/uv, Python/pip, Node, Rust, Go, Java/Maven, Java/Gradle, Ruby).
2. Emit an explanatory stub for unknown stacks, not bare whitespace.
3. NEVER include cloglog-specific commands (`worktree-infra.sh`, the
   close-off-task curl, `shutdown-artifacts/` reset). Those live only in
   cloglog's hand-written copy of `.cloglog/on-worktree-create.sh` and are
   project-specific extensions.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"

STACK_HEADINGS = [
    "**Python with uv**",
    "**Python without uv**",
    "**Node.js**",
    "**Rust**",
    "**Go**",
    "**Java / Maven**",
    "**Java / Gradle**",
    "**Ruby / Bundler**",
]


def _read() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing"
    return INIT_SKILL.read_text(encoding="utf-8")


def _step4b_body(body: str) -> str:
    """Extract the text of Step 4b (between '### 4b.' and the next '### ')."""
    lines = body.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith("### 4b."):
            in_section = True
            out.append(line)
            continue
        if in_section:
            if line.startswith("### ") and not line.startswith("### 4b."):
                break
            out.append(line)
    assert out, "Could not locate ### 4b. section in init SKILL.md"
    return "\n".join(out)


def _block_after(text: str, heading: str) -> str:
    """Return the first ```bash fenced block after `heading`."""
    idx = text.find(heading)
    assert idx != -1, f"Heading {heading!r} not found in Step 4b"
    fence_open = text.find("```bash", idx)
    assert fence_open != -1, f"No ```bash block after {heading!r}"
    fence_close = text.find("```", fence_open + len("```bash"))
    assert fence_close != -1, f"Unterminated ```bash block after {heading!r}"
    return text[fence_open + len("```bash") : fence_close].strip()


# ---------------------------------------------------------------------------
# Presence pins — every documented stack must produce a non-empty script
# ---------------------------------------------------------------------------


def test_every_stack_block_is_nonempty() -> None:
    """Each tech-stack heading in Step 4b must be followed by a non-empty bash
    block whose body contains at least one real command (not just shebang +
    set -e)."""
    section = _step4b_body(_read())
    for heading in STACK_HEADINGS:
        block = _block_after(section, heading)
        # Strip shebang, `set -euo pipefail`, and `cd "${WORKTREE_PATH...}"` —
        # what's left must contain a real install/build command.
        residual = re.sub(r"^#!/usr/bin/env bash\s*$", "", block, flags=re.M)
        residual = re.sub(r"^set -euo pipefail\s*$", "", residual, flags=re.M)
        residual = re.sub(r'^cd "\$\{WORKTREE_PATH[^"]*"\s*$', "", residual, flags=re.M)
        residual = residual.strip()
        assert residual, (
            f"Stack {heading!r} has no real command after the boilerplate — "
            "init would generate an empty bootstrap for projects on this stack."
        )


def test_unknown_stack_stub_has_explanatory_comment() -> None:
    """The unknown-stack fallback must include a comment explaining what to
    add — not just a bare shebang."""
    section = _step4b_body(_read())
    block = _block_after(section, "**Unknown stack**")
    comment_lines = [
        ln for ln in block.splitlines() if ln.strip().startswith("#") and "!" not in ln
    ]
    assert comment_lines, (
        "Unknown-stack fallback must include explanatory comment lines, not just a shebang."
    )
    assert any("WORKTREE_PATH" in ln for ln in comment_lines), (
        "Unknown-stack fallback comment should mention WORKTREE_PATH so "
        "operators know the env contract."
    )


# ---------------------------------------------------------------------------
# Absence pins — cloglog-specific commands must not leak into init's templates
# ---------------------------------------------------------------------------


_FORBIDDEN_IN_TEMPLATES = [
    "worktree-infra.sh",
    "/api/v1/agents/close-off-task",
    "shutdown-artifacts",
]


def test_step4b_templates_have_no_cloglog_specific_commands() -> None:
    """The bash blocks init emits for `on-worktree-create.sh` must not contain
    cloglog dogfood-specific machinery. Those belong in cloglog's hand-written
    copy, not in the generic init template."""
    section = _step4b_body(_read())
    headings = STACK_HEADINGS + ["**Unknown stack**"]
    for heading in headings:
        block = _block_after(section, heading)
        for needle in _FORBIDDEN_IN_TEMPLATES:
            assert needle not in block, (
                f"Stack template {heading!r} contains cloglog-specific "
                f"command {needle!r}. init must emit only generic "
                "dependency-fetch commands; close-off-task POST and "
                "worktree-infra.sh are dogfood extensions, not init output."
            )


def test_step4b_documents_cloglog_extensions_as_out_of_scope() -> None:
    """Step 4b must explicitly call out close-off-task POST and worktree-infra.sh
    as cloglog-specific extensions, so a downstream reader knows they are NOT
    part of init's generated script."""
    section = _step4b_body(_read())
    assert "Cloglog-specific extensions" in section, (
        "Step 4b must include a 'Cloglog-specific extensions' note that lists "
        "close-off-task POST and worktree-infra.sh as out-of-scope for init."
    )
    assert "worktree-infra.sh" in section, (
        "Step 4b's cloglog-extensions note must name worktree-infra.sh "
        "explicitly so readers can grep for it."
    )
    assert "close-off-task" in section, (
        "Step 4b's cloglog-extensions note must name the close-off-task endpoint explicitly."
    )
