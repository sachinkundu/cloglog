"""Pin tests for T-467: Jinja2-rendered exemption.md.

Covers:
1. Snapshot — fixed inputs produce a byte-equal exemption.md.
2. Special-chars — reasoning containing backticks, ``$()``, and pipes
   round-trips verbatim (the heredoc predecessor would execute them).
3. Round-trip — the rendered file passes ``scripts/check-demo.sh``.
4. Missing-key gate — ``check-demo.sh`` rejects an exemption.md that is
   missing any of the four required frontmatter keys (one negative test
   per key).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_SCRIPT = REPO_ROOT / "plugins" / "cloglog" / "scripts" / "render_template.py"
TEMPLATE = REPO_ROOT / "plugins" / "cloglog" / "templates" / "exemption.md.template"
CHECK_DEMO_SH = REPO_ROOT / "scripts" / "check-demo.sh"

_FIXED_DIFF_HASH = "a" * 64
_FIXED_GENERATED_AT = "2026-05-05T12:00:00Z"
_FIXED_REASONING = "Pure internal refactor. No user-observable behaviour change."
_FIXED_FILE_LIST = "- src/foo.py\n- src/bar.py"

EXPECTED_EXEMPTION = (
    f"---\n"
    f"verdict: no_demo\n"
    f"diff_hash: {_FIXED_DIFF_HASH}\n"
    f"classifier: demo-classifier\n"
    f"generated_at: {_FIXED_GENERATED_AT}\n"
    f"---\n"
    f"\n"
    f"## Why no demo\n"
    f"\n"
    f"{_FIXED_REASONING}\n"
    f"\n"
    f"## Changed files\n"
    f"\n"
    f"{_FIXED_FILE_LIST}\n"
)


def _render(tmp_path: Path, **render_vars: str) -> Path:
    out = tmp_path / "exemption.md"
    cmd = [
        "uv",
        "run",
        "--with",
        "jinja2",
        str(RENDER_SCRIPT),
        "--template",
        str(TEMPLATE),
        "--output",
        str(out),
    ]
    for k, v in render_vars.items():
        cmd += ["--var", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, (
        f"render_template.py failed.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    return out


def test_snapshot_fixed_inputs(tmp_path: Path) -> None:
    """Fixed inputs produce byte-equal exemption.md."""
    out = _render(
        tmp_path,
        diff_hash=_FIXED_DIFF_HASH,
        generated_at=_FIXED_GENERATED_AT,
        reasoning=_FIXED_REASONING,
        file_list=_FIXED_FILE_LIST,
    )
    got = out.read_text(encoding="utf-8")
    assert got == EXPECTED_EXEMPTION, f"Rendered output does not match snapshot.\ngot:\n{got!r}"


def test_special_chars_round_trip(tmp_path: Path) -> None:
    """Reasoning containing backticks, $(), and pipes must survive verbatim."""
    nasty = "uses `backticks`, $(subshell), pipe | symbol, and $VAR"
    out = _render(
        tmp_path,
        diff_hash=_FIXED_DIFF_HASH,
        generated_at=_FIXED_GENERATED_AT,
        reasoning=nasty,
        file_list="- src/module.py",
    )
    content = out.read_text(encoding="utf-8")
    assert nasty in content, f"Special characters were not preserved verbatim.\ngot:\n{content!r}"
    assert "`backticks`" in content
    assert "$(subshell)" in content
    assert "pipe | symbol" in content
    assert "$VAR" in content


# ---------------------------------------------------------------------------
# check-demo.sh gate tests
# ---------------------------------------------------------------------------

_GIT_ENV_BASE = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

_DEMO_ALLOWLIST = (
    "demo_allowlist_paths: '"
    r"^docs/|^CLAUDE\.md|^\.claude/|^\.cloglog/|^scripts/|^\.github/|"
    r"^tests/|^Makefile$|^plugins/[^/]+/(hooks|skills|agents|templates)/|"
    r"^pyproject\.toml$|^ruff\.toml$|package-lock\.json$|\.lock$"
    "'\n"
)


def _git(args: list[str], repo: Path, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def _init_repo(tmp_path: Path) -> dict[str, str]:
    env = {**os.environ, **_GIT_ENV_BASE}
    _git(["init", "-b", "main", "."], tmp_path, env)
    (tmp_path / "README.md").write_text("# test\n")
    _git(["add", "README.md"], tmp_path, env)
    _git(["commit", "-m", "initial"], tmp_path, env)
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, env=env, text=True
    ).strip()
    _git(["update-ref", "refs/remotes/origin/main", head], tmp_path, env)
    _git(["checkout", "-b", "feature-branch"], tmp_path, env)
    cloglog_dir = tmp_path / ".cloglog"
    cloglog_dir.mkdir(exist_ok=True)
    (cloglog_dir / "config.yaml").write_text(_DEMO_ALLOWLIST)
    # Add a non-allowlisted file so check-demo.sh proceeds past the
    # code-change guard and reaches the demo-or-exemption check.
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "handler.py").write_text("def handler(): return 1\n")
    _git(["add", "src/handler.py"], tmp_path, env)
    _git(["commit", "-m", "add handler"], tmp_path, env)
    return env


def _current_diff_hash(repo: Path, env: dict[str, str]) -> str:
    merge_base = subprocess.check_output(
        ["git", "merge-base", "origin/main", "HEAD"],
        cwd=repo,
        env=env,
        text=True,
    ).strip()
    diff = subprocess.check_output(
        ["git", "diff", merge_base, "HEAD", "--", ".", ":(exclude)docs/demos/"],
        cwd=repo,
        env=env,
        text=True,
    )
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def _write_full_exemption(
    repo: Path,
    *,
    verdict: str | None = "no_demo",
    diff_hash: str | None,
    classifier: str | None = "demo-classifier",
    generated_at: str | None = "2026-05-05T12:00:00Z",
) -> None:
    """Write an exemption.md with any of the four keys optionally omitted."""
    demo_dir = repo / "docs" / "demos" / "feature-branch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    if verdict is not None:
        lines.append(f"verdict: {verdict}")
    if diff_hash is not None:
        lines.append(f"diff_hash: {diff_hash}")
    if classifier is not None:
        lines.append(f"classifier: {classifier}")
    if generated_at is not None:
        lines.append(f"generated_at: {generated_at}")
    lines += ["---", "", "## Why no demo", "", "Pure refactor.", ""]
    (demo_dir / "exemption.md").write_text("\n".join(lines))


def _run_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECK_DEMO_SH)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_round_trip_rendered_exemption_passes_gate(tmp_path: Path) -> None:
    """render_template.py output passes check-demo.sh with correct diff_hash."""
    env = _init_repo(tmp_path)
    diff_hash = _current_diff_hash(tmp_path, env)
    demo_dir = tmp_path / "docs" / "demos" / "feature-branch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    render_out = _render(
        tmp_path / "render_out",
        diff_hash=diff_hash,
        generated_at="2026-05-05T12:00:00Z",
        reasoning="Pure internal refactor. No user-observable change.",
        file_list="- src/handler.py",
    )
    (demo_dir / "exemption.md").write_bytes(render_out.read_bytes())
    _git(["add", "docs/demos/"], tmp_path, env)
    _git(["commit", "-m", "add exemption"], tmp_path, env)
    result = _run_gate(tmp_path, env)
    assert result.returncode == 0, (
        f"Round-trip rendered exemption was rejected.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "Exemption verified" in result.stdout


def test_gate_rejects_missing_verdict(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    diff_hash = _current_diff_hash(tmp_path, env)
    _write_full_exemption(tmp_path, verdict=None, diff_hash=diff_hash)
    result = _run_gate(tmp_path, env)
    assert result.returncode != 0
    assert "missing required frontmatter key: verdict" in result.stdout, (
        f"Expected rejection for missing 'verdict'.\nstdout: {result.stdout!r}"
    )


def test_gate_rejects_missing_diff_hash(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_full_exemption(tmp_path, diff_hash=None)
    result = _run_gate(tmp_path, env)
    assert result.returncode != 0
    assert "missing required frontmatter key: diff_hash" in result.stdout, (
        f"Expected rejection for missing 'diff_hash'.\nstdout: {result.stdout!r}"
    )


def test_gate_rejects_missing_classifier(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    diff_hash = _current_diff_hash(tmp_path, env)
    _write_full_exemption(tmp_path, classifier=None, diff_hash=diff_hash)
    result = _run_gate(tmp_path, env)
    assert result.returncode != 0
    assert "missing required frontmatter key: classifier" in result.stdout, (
        f"Expected rejection for missing 'classifier'.\nstdout: {result.stdout!r}"
    )


def test_gate_rejects_missing_generated_at(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    diff_hash = _current_diff_hash(tmp_path, env)
    _write_full_exemption(tmp_path, generated_at=None, diff_hash=diff_hash)
    result = _run_gate(tmp_path, env)
    assert result.returncode != 0
    assert "missing required frontmatter key: generated_at" in result.stdout, (
        f"Expected rejection for missing 'generated_at'.\nstdout: {result.stdout!r}"
    )
