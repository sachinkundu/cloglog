"""Pin test: gunicorn invocations in Makefile must include --capture-output.

T-231 — without --capture-output, application-level stderr (FastAPI tracebacks,
codex CLI invocation errors, review_engine exceptions) is lost when gunicorn
runs in --daemon mode. Both the `prod` and `prod-bg` recipes invoke gunicorn,
and both must capture worker stdout/stderr into --error-logfile.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


def _gunicorn_invocations(text: str) -> list[str]:
    """Return each gunicorn invocation as a single joined string (line continuations resolved)."""
    invocations: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if "uv run gunicorn" in lines[i]:
            joined = lines[i]
            while joined.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                joined = joined.rstrip()[:-1] + " " + lines[i]
            invocations.append(joined)
        i += 1
    return invocations


def test_makefile_has_two_gunicorn_invocations() -> None:
    invocations = _gunicorn_invocations(MAKEFILE.read_text())
    assert len(invocations) == 2, (
        f"expected exactly two gunicorn invocations (prod + prod-bg), found {len(invocations)}"
    )


def test_each_gunicorn_invocation_passes_capture_output() -> None:
    invocations = _gunicorn_invocations(MAKEFILE.read_text())
    for inv in invocations:
        assert re.search(r"(^|\s)--capture-output(\s|$)", inv), (
            f"gunicorn invocation missing --capture-output (T-231): {inv!r}"
        )
