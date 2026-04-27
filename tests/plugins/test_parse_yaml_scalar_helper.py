"""T-312: shared YAML scalar-key helper for plugin hooks.

Pin tests for plugins/cloglog/hooks/lib/parse-yaml-scalar.sh. The helper
replaces 4 `python3 -c 'import yaml'` sites that violated
docs/invariants.md:76 (system python3 lacks PyYAML on portable hosts).
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPER = REPO_ROOT / "plugins/cloglog/hooks/lib/parse-yaml-scalar.sh"


def _run_helper(cfg: Path, key: str, default: str = "") -> str:
    """Source the helper in a fresh subshell and return the scalar value."""
    script = textwrap.dedent(f"""
        # shellcheck source=/dev/null
        source "{HELPER}"
        read_yaml_scalar "{cfg}" "{key}" "{default}"
    """)
    out = subprocess.run(
        ["bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.rstrip("\n")


def test_helper_file_exists_and_is_readable() -> None:
    assert HELPER.exists(), f"{HELPER} missing"
    body = HELPER.read_text(encoding="utf-8")
    assert "read_yaml_scalar()" in body
    # Non-negotiable: stdlib-only — must not pull in pyyaml.
    assert "import yaml" not in body, (
        "helper must remain stdlib-only — `import yaml` defeats its entire purpose"
    )


def test_reads_unquoted_scalar(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("backend_url: http://127.0.0.1:8001\n")
    assert _run_helper(cfg, "backend_url") == "http://127.0.0.1:8001"


def test_reads_double_quoted_scalar(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text('quality_command: "make quality"\n')
    assert _run_helper(cfg, "quality_command") == "make quality"


def test_reads_single_quoted_scalar(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project_id: 'abcd-1234'\n")
    assert _run_helper(cfg, "project_id") == "abcd-1234"


def test_strips_trailing_comment(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("backend_url: http://localhost:8000  # dev default\n")
    assert _run_helper(cfg, "backend_url") == "http://localhost:8000"


def test_missing_key_returns_default(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project_id: abc\n")
    assert _run_helper(cfg, "backend_url", "http://fallback:8000") == ("http://fallback:8000")


def test_missing_key_no_default_returns_empty(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("project_id: abc\n")
    assert _run_helper(cfg, "backend_url") == ""


def test_missing_file_returns_default(tmp_path: Path) -> None:
    cfg = tmp_path / "absent.yaml"
    assert _run_helper(cfg, "backend_url", "http://fallback:8000") == ("http://fallback:8000")


def test_first_match_wins_when_key_repeated(tmp_path: Path) -> None:
    """Defensive — head -n1 in the helper picks the first occurrence."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("backend_url: http://first:8000\nbackend_url: http://second:9000\n")
    assert _run_helper(cfg, "backend_url") == "http://first:8000"


def test_helper_works_without_pyyaml_in_env(tmp_path: Path) -> None:
    """Pin: helper must succeed even when `import yaml` would fail.

    Simulates the portable-host case where global python3 lacks PyYAML.
    The helper is shell-only so it should not even invoke python3, but we
    explicitly assert that running under a python-import-broken env still
    returns the right value.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text("backend_url: http://no-yaml:8000\n")

    script = textwrap.dedent(f"""
        # shellcheck source=/dev/null
        source "{HELPER}"
        read_yaml_scalar "{cfg}" "backend_url"
    """)
    out = subprocess.run(
        ["env", "-i", "PATH=/usr/bin:/bin", "PYTHONPATH=/dev/null", "bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert out.stdout.rstrip("\n") == "http://no-yaml:8000"
