"""T-466: pin tests for plugins/cloglog/scripts/set_yaml_keys.py.

Three test categories required by the task spec:
  1. Snapshot — fixture config.yaml + values → expected output (both
     update-in-place and append branches).
  2. Special-chars regression — values containing &, |, /, \\, spaces.
  3. Duplicate-key footgun — second invocation does NOT silently shadow.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = REPO_ROOT / "plugins/cloglog/scripts/set_yaml_keys.py"


def _run(config: Path, *assignments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), str(config), *assignments],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Basic hygiene
# ---------------------------------------------------------------------------


def test_helper_file_exists() -> None:
    assert HELPER.exists(), f"{HELPER} not found"


def test_no_pyyaml_import() -> None:
    body = HELPER.read_text(encoding="utf-8")
    assert "import yaml" not in body, "helper must remain stdlib-only"


# ---------------------------------------------------------------------------
# Snapshot: append branch (key absent from existing file)
# ---------------------------------------------------------------------------


def test_append_all_keys_to_existing_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("reviewer_bot_logins: [codex[bot]]\n")

    result = _run(
        cfg,
        "project=my-project",
        "project_id=abc-123",
        "backend_url=http://127.0.0.1:8001",
    )
    assert result.returncode == 0, result.stderr

    content = cfg.read_text()
    assert "reviewer_bot_logins: [codex[bot]]" in content
    assert "project: my-project" in content
    assert "project_id: abc-123" in content
    assert "backend_url: http://127.0.0.1:8001" in content


def test_creates_file_when_absent(tmp_path: Path) -> None:
    cfg = tmp_path / ".cloglog" / "config.yaml"
    # File and parent dir do not exist yet.

    result = _run(cfg, "project=new-proj", "project_id=uuid-1")
    assert result.returncode == 0, result.stderr

    assert cfg.exists()
    content = cfg.read_text()
    assert "project: new-proj\n" in content
    assert "project_id: uuid-1\n" in content


# ---------------------------------------------------------------------------
# Snapshot: update branch (key present)
# ---------------------------------------------------------------------------


def test_updates_existing_keys_in_place(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project: old-slug\nproject_id: old-id\nbackend_url: http://old:8000\n")

    result = _run(
        cfg,
        "project=new-slug",
        "project_id=new-id",
        "backend_url=http://new:9000",
    )
    assert result.returncode == 0, result.stderr

    lines = cfg.read_text().splitlines()
    assert lines == [
        "project: new-slug",
        "project_id: new-id",
        "backend_url: http://new:9000",
    ]


def test_update_preserves_surrounding_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "reviewer_bot_logins: [codex[bot]]\n"
        "project: old-slug\n"
        "project_id: old-id\n"
        "backend_url: http://old:8000\n"
        "quality_command: make quality\n"
    )

    result = _run(cfg, "project=new-slug", "backend_url=http://new:9000")
    assert result.returncode == 0, result.stderr

    content = cfg.read_text()
    assert "reviewer_bot_logins: [codex[bot]]" in content
    assert "quality_command: make quality" in content
    assert "project: new-slug" in content
    assert "backend_url: http://new:9000" in content
    # Untouched key must remain unchanged.
    assert "project_id: old-id" in content


def test_update_mixed_append_and_replace(tmp_path: Path) -> None:
    """One key present (update), one absent (append)."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project: old-slug\n")

    result = _run(cfg, "project=new-slug", "backend_url=http://127.0.0.1:8001")
    assert result.returncode == 0, result.stderr

    content = cfg.read_text()
    assert "project: new-slug" in content
    assert "backend_url: http://127.0.0.1:8001" in content
    # The old value must not appear.
    assert "old-slug" not in content


# ---------------------------------------------------------------------------
# Special-chars regression (T-466 primary motivation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "special_value",
    [
        "value&with&ampersand",
        "value|with|pipe",
        "http://host:8001/api/v1",
        r"back\slash",
        "value with spaces",
        r"combined &|/\ chars",
    ],
)
def test_special_chars_round_trip(tmp_path: Path, special_value: str) -> None:
    cfg = tmp_path / "config.yaml"

    # Append branch
    result = _run(cfg, f"backend_url={special_value}")
    assert result.returncode == 0, result.stderr
    assert f"backend_url: {special_value}" in cfg.read_text()

    # Update branch
    result2 = _run(cfg, f"backend_url={special_value}_v2")
    assert result2.returncode == 0, result2.stderr
    assert f"backend_url: {special_value}_v2" in cfg.read_text()
    assert special_value + "\n" not in cfg.read_text()


# ---------------------------------------------------------------------------
# Trailing-newline regression (codex session-1 finding)
# ---------------------------------------------------------------------------


def test_append_does_not_glue_onto_last_line_without_trailing_newline(
    tmp_path: Path,
) -> None:
    """File ending without \\n must not have appended key glued to previous line."""
    cfg = tmp_path / "config.yaml"
    # Write without trailing newline — some editors produce this.
    cfg.write_bytes(b"reviewer_bot_logins: [codex[bot]]")

    result = _run(cfg, "project=my-slug")
    assert result.returncode == 0, result.stderr

    content = cfg.read_text()
    lines = content.splitlines()
    assert any(ln == "project: my-slug" for ln in lines), (
        f"appended key glued to previous line: {lines}"
    )
    assert all("reviewer_bot_logins" not in ln or "project" not in ln for ln in lines), (
        f"keys merged onto one line: {lines}"
    )


# ---------------------------------------------------------------------------
# Duplicate-key footgun: second invocation must UPDATE, not append
# ---------------------------------------------------------------------------


def test_second_invocation_updates_not_appends(tmp_path: Path) -> None:
    """Running the helper twice must not produce duplicate keys."""
    cfg = tmp_path / "config.yaml"

    _run(cfg, "project=first")
    _run(cfg, "project=second")

    lines = [ln for ln in cfg.read_text().splitlines() if ln.startswith("project:")]
    assert len(lines) == 1, f"duplicate key found: {lines}"
    assert lines[0] == "project: second"


def test_second_invocation_all_three_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"

    _run(
        cfg,
        "project=slug-v1",
        "project_id=id-v1",
        "backend_url=http://v1:8001",
    )
    _run(
        cfg,
        "project=slug-v2",
        "project_id=id-v2",
        "backend_url=http://v2:9002",
    )

    content = cfg.read_text()
    for key in ("project", "project_id", "backend_url"):
        matching = [ln for ln in content.splitlines() if ln.startswith(f"{key}:")]
        assert len(matching) == 1, f"duplicate key {key!r}: {matching}"

    assert "slug-v2" in content
    assert "id-v2" in content
    assert "http://v2:9002" in content
    # Old values must be gone.
    assert "slug-v1" not in content
    assert "id-v1" not in content
    assert "http://v1:8001" not in content


# ---------------------------------------------------------------------------
# CLI error cases
# ---------------------------------------------------------------------------


def test_missing_args_exits_nonzero(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_equals_sign_exits_nonzero(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    result = _run(cfg, "no-equals-here")
    assert result.returncode != 0
    assert "key=value" in result.stderr
