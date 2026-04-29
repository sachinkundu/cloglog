"""T-346 pin tests: init's Step 6a backfill of ``repo_url``.

Asserts the SKILL.md surface keeps the load-bearing pieces in place:

1. The bash block under "### 6a." canonicalizes the URL with the same
   shape ``src/board/repo_url.py::normalize_repo_url`` produces (strip
   ``.git``, convert SSH→HTTPS, drop trailing slash).
2. The skill mentions ``mcp__cloglog__update_project`` so the backfill
   call is reachable via MCP, not a curl fallback.
3. The "Re-running init is safe" preamble names the auto-repair so an
   operator running ``/cloglog init`` on a project with empty
   ``repo_url`` knows what will happen.

These are *presence* pins (per CLAUDE.md "Presence-pins survive narrowing;
absence-pins catch returns") — the substance must remain even if the
prose is reworded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src.board.repo_url import normalize_repo_url

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"


def _read_skill() -> str:
    return INIT_SKILL.read_text(encoding="utf-8")


def _section(body: str, start_marker: str, stop_prefix: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith(start_marker):
            capturing = True
            out.append(line)
            continue
        if capturing:
            if line.startswith(stop_prefix) and not line.startswith(start_marker):
                break
            out.append(line)
    assert out, f"Could not locate {start_marker!r} section"
    return "\n".join(out)


def test_step6a_mentions_update_project_mcp_tool() -> None:
    body = _read_skill()
    step6a = _section(body, "### 6a.", "### ")
    assert "mcp__cloglog__update_project" in step6a, (
        "Step 6a must call mcp__cloglog__update_project to backfill the "
        "project's repo_url. Without this MCP call the backfill silently "
        "doesn't happen and the webhook router stays broken."
    )


def test_step6a_canonicalizes_url() -> None:
    body = _read_skill()
    step6a = _section(body, "### 6a.", "### ")
    # All four canonicalization steps must appear in the bash block —
    # missing any one leaves a class of inputs unmatched against the
    # webhook resolver's endswith() lookup.
    for needle in [
        "git@github.com:",  # SSH→HTTPS conversion
        "https://github.com/",  # destination form
        ".git",  # strip trailing .git
    ]:
        assert needle in step6a, (
            f"Step 6a must reference {needle!r} as part of the canonical-URL "
            "transform. Each missing piece leaves a class of remote URLs "
            "(SSH, .git, http) silently incompatible with the backend's "
            "endswith() webhook lookup."
        )


def test_skill_preamble_mentions_repo_url_auto_repair() -> None:
    body = _read_skill()
    # "Re-running init is safe" preamble lives near the top.
    assert "repo_url" in body, "SKILL.md must mention repo_url somewhere"
    # The auto-repair callout names the backfill explicitly.
    assert re.search(
        r"Auto-repair.*repo_url|repo_url.*backfill",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    ), (
        "SKILL.md preamble must surface the repo_url backfill under "
        "'Auto-repair on re-run' — operators need to know re-running init "
        "will repair an empty repo_url, not just the legacy mcpServers move."
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("git@github.com:owner/repo.git", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo.git", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo/", "https://github.com/owner/repo"),
        ("  https://github.com/owner/repo  ", "https://github.com/owner/repo"),
    ],
)
def test_step6a_bash_block_matches_python_normalizer(raw: str, expected: str) -> None:
    """Execute the Step 6a canonicalization snippet and compare against
    ``normalize_repo_url`` — the two MUST produce identical bytes for
    each canonical input class. If they diverge, the init shell pre-write
    and the backend post-write disagree and re-running init writes
    different bytes on each pass.
    """
    body = _read_skill()
    step6a = _section(body, "### 6a.", "### ")
    # Pull the bash snippet that defines CANONICAL_URL. Iterate over every
    # ```bash``` block in Step 6a and keep the one that mentions
    # CANONICAL_URL — a non-greedy ``(.*?CANONICAL_URL.*?)`` between
    # ```bash and ``` would slurp prose between sibling code blocks.
    snippets = re.findall(r"```bash\n(.*?)```", step6a, re.DOTALL)
    matching = [s for s in snippets if "CANONICAL_URL" in s]
    assert matching, "No ```bash``` block defining CANONICAL_URL in Step 6a"
    snippet = matching[0]

    # Drive the snippet with raw and read CANONICAL_URL out via printf
    # to a sentinel stdout line — keeps stdout deterministic across
    # whatever echo lines the snippet itself emits.
    driver = f"ORIGIN_URL={raw!r}\n" + snippet + "\nprintf 'RESULT=%s\\n' \"$CANONICAL_URL\"\n"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", driver],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Step 6a bash snippet failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    last = [
        line[len("RESULT=") :] for line in result.stdout.splitlines() if line.startswith("RESULT=")
    ]
    assert last, f"No RESULT= line in {result.stdout!r}"
    assert last[-1] == expected, (
        f"Step 6a snippet produced {last[-1]!r} for {raw!r}, "
        f"expected {expected!r}. Drift between the shell pre-write and "
        "src/board/repo_url.py::normalize_repo_url means init writes "
        "different bytes than the backend stores."
    )
    # And the python normalizer agrees with the same expectation.
    assert normalize_repo_url(raw) == expected
