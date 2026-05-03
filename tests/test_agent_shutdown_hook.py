"""Regression guard: T-243.

`plugins/cloglog/hooks/agent-shutdown.sh` MUST write a structured
`agent_unregistered` event to the project-root inbox on SessionEnd, even
when the agent itself skipped the explicit emit (the hook is the
best-effort backstop). The event must carry absolute artifact paths so the
main agent's close-wave flow can read them after the worktree is torn down.

See `docs/design/agent-lifecycle.md` §2 step 5.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "plugins" / "cloglog" / "hooks" / "agent-shutdown.sh"


def _run_hook(cwd: Path, env: dict[str, str]) -> None:
    payload = json.dumps({"cwd": str(cwd)})
    # The hook's curl-to-unregister-by-path step is gated on a non-empty
    # API key; with HOME pointing at an empty dir and CLOGLOG_API_KEY unset,
    # no network call is attempted and the test stays hermetic.
    subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def stub_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Scratch main repo + attached worktree, returning (main_root, wt_path)."""
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        check=True,
    )
    # Normalize to `main` so the hook's `git log main..HEAD` resolves; local
    # git versions may default to `master`.
    subprocess.run(["git", "-C", str(main), "branch", "-M", "main"], check=True)
    wt = tmp_path / "wt-sim"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt-sim"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "T-243 hook backstop test",
            "-q",
        ],
        check=True,
    )
    (main / ".cloglog").mkdir()
    (main / ".cloglog" / "inbox").touch()
    return main, wt


def test_hook_writes_agent_unregistered_backstop(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    main, wt = stub_worktree
    # Empty HOME so ~/.cloglog/credentials is absent; PATH kept so git/bash resolve.
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    inbox = (main / ".cloglog" / "inbox").read_text().strip().splitlines()
    assert inbox, "main agent inbox must receive the backstop event"
    event = json.loads(inbox[-1])

    assert event["type"] == "agent_unregistered"
    assert event["worktree"] == "wt-sim"
    assert event["reason"] == "best_effort_backstop_from_session_end_hook"
    assert event["ts"], "ts must be present (ISO-8601 from `date -Iseconds`)"

    artifacts = event["artifacts"]
    # Absolute paths — the main agent reads these after the worktree is torn
    # down and the relative root is gone by then.
    assert Path(artifacts["work_log"]).is_absolute()
    assert Path(artifacts["learnings"]).is_absolute()
    assert Path(artifacts["work_log"]).exists()
    assert Path(artifacts["learnings"]).exists()


def test_hook_derives_tasks_completed_from_git_log(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    main, wt = stub_worktree
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    event = json.loads((main / ".cloglog" / "inbox").read_text().strip().splitlines()[-1])
    # The sole commit on the worktree references T-243; the hook's
    # `git log main..HEAD | jq -Rn 'scan("T-[0-9]+")'` must pick it up.
    assert event["tasks_completed"] == ["T-243"]


def test_hook_emits_prs_map_field(stub_worktree: tuple[Path, Path], tmp_path: Path) -> None:
    """T-262: the hook MUST emit a `prs` field (map of T-NNN -> PR URL).

    Best-effort enrichment via `gh pr list` runs only when `gh` is on PATH
    and the worktree's branch has a merged PR; in this test environment
    `gh` is not authenticated against the stub repo, so the value is `{}`.
    The pin is on the field's existence and shape (an object), not its
    contents — supervisors interpret missing keys as 'hook didn't know.'
    """
    main, wt = stub_worktree
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    event = json.loads((main / ".cloglog" / "inbox").read_text().strip().splitlines()[-1])
    assert "prs" in event, "agent_unregistered MUST carry a `prs` field (T-262)"
    assert isinstance(event["prs"], dict), "`prs` MUST be a JSON object"
    # Backward-compat pin: tasks_completed remains a flat list of IDs so
    # existing parsers (work-log generators, supervisor scripts) keep
    # working without changes. T-262 chose Option A (parallel map) for
    # exactly this reason.
    assert isinstance(event["tasks_completed"], list)
    assert all(isinstance(t, str) for t in event["tasks_completed"])


def test_hook_emits_empty_tasks_array_when_no_refs_in_commits(
    tmp_path: Path,
) -> None:
    """A worktree whose commits carry no T-NNN reference (e.g., a research
    branch) must still produce a well-formed event. `tasks_completed` is an
    empty JSON array, never absent and never null."""
    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(main),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "init",
            "-q",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(main), "branch", "-M", "main"], check=True)
    wt = tmp_path / "wt-no-refs"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt-no-refs"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(wt),
            "-c",
            "user.email=a@b",
            "-c",
            "user.name=a",
            "commit",
            "--allow-empty",
            "-m",
            "chore: bump deps",
            "-q",
        ],
        check=True,
    )
    (main / ".cloglog").mkdir()
    (main / ".cloglog" / "inbox").touch()

    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)

    event = json.loads((main / ".cloglog" / "inbox").read_text().strip().splitlines()[-1])
    assert event["tasks_completed"] == []


def test_hook_resolves_per_project_credentials(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """T-382 regression: when the project's API key only lives under
    ~/.cloglog/credentials.d/<slug>, the hook MUST resolve it and run the
    unregister POST. Before T-382 the hook only consulted env and the legacy
    global file, so on multi-project hosts the SessionEnd unregister was
    silently skipped (logged "no API_KEY") and the worktree stayed
    registered until the heartbeat timeout.

    The unregister POST itself fails (no backend in tests), but the
    debug-log line distinguishes the two branches: the per-project resolver
    must take "calling unregister-by-path", not "no API_KEY — skipping".
    """
    main, wt = stub_worktree
    # Stamp `project: t382test` into a config visible from the worktree.
    # In production, .cloglog/config.yaml is a tracked file so the
    # checkout sees it; the test fixture's worktree is a sibling of
    # main rather than nested under it, so we write the config inside
    # the worktree where find_config() walks up from $CWD will see it.
    (wt / ".cloglog").mkdir(exist_ok=True)
    (wt / ".cloglog" / "config.yaml").write_text(
        "project: t382test\nbackend_url: http://127.0.0.1:1\n"
    )
    # Also stamp it into main so the MAIN_INBOX path (and any other
    # main-repo lookups) resolve identically.
    (main / ".cloglog" / "config.yaml").write_text(
        "project: t382test\nbackend_url: http://127.0.0.1:1\n"
    )
    fake_home = tmp_path / "home"
    cred_dir = fake_home / ".cloglog" / "credentials.d"
    cred_dir.mkdir(parents=True)
    cred_path = cred_dir / "t382test"
    cred_path.write_text("CLOGLOG_API_KEY=per-project-resolved\n")
    os.chmod(cred_path, 0o600)

    debug_log = tmp_path / "agent-shutdown-debug.log"
    env = {
        "HOME": str(fake_home),
        "PATH": os.environ["PATH"],
        # Redirect the hook's debug log to a per-test file by overriding
        # /tmp via a TMPDIR-style trick is not viable — the hook hard-codes
        # /tmp/agent-shutdown-debug.log. Instead, snapshot the file
        # before/after and assert the new lines.
    }
    before = (
        Path("/tmp/agent-shutdown-debug.log").read_text()
        if Path("/tmp/agent-shutdown-debug.log").exists()
        else ""
    )
    _run_hook(wt, env)
    after = Path("/tmp/agent-shutdown-debug.log").read_text()
    new_lines = after[len(before) :]
    # Quietly absorb the after-snapshot suppressing the unused-variable warning.
    _ = debug_log

    assert "calling unregister-by-path" in new_lines, (
        "Hook must take the API_KEY-present branch when only "
        "~/.cloglog/credentials.d/<slug> exists. Debug log delta:\n" + new_lines
    )
    assert "no API_KEY" not in new_lines, (
        "Per-project resolver regressed — hook fell through to 'no API_KEY' "
        "branch. Debug log delta:\n" + new_lines
    )


def test_hook_resolves_per_project_credentials_with_single_quoted_slug(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """T-382 codex round 4: a YAML config with `project: 'beta'` (single
    quotes — fully valid YAML, accepted by every other reader) MUST be
    slug-stripped just like double quotes. The shared scalar reader
    (lib/parse-yaml-scalar.sh) handles this correctly; this pin makes
    sure the credential resolver routes through that helper instead of
    rolling its own quote-stripping that omits one of the quote shapes.
    """
    main, wt = stub_worktree
    # Use single quotes — a previous custom parser stripped only " ",
    # leaving 'beta' as slug-invalid and falling back to basename.
    (wt / ".cloglog").mkdir(exist_ok=True)
    (wt / ".cloglog" / "config.yaml").write_text(
        "project: 'beta'\nbackend_url: http://127.0.0.1:1\n"
    )
    (main / ".cloglog" / "config.yaml").write_text(
        "project: 'beta'\nbackend_url: http://127.0.0.1:1\n"
    )
    fake_home = tmp_path / "home-q"
    cred_dir = fake_home / ".cloglog" / "credentials.d"
    cred_dir.mkdir(parents=True)
    cred_path = cred_dir / "beta"
    cred_path.write_text("CLOGLOG_API_KEY=beta-quoted-key\n")
    os.chmod(cred_path, 0o600)

    env = {"HOME": str(fake_home), "PATH": os.environ["PATH"]}
    before = (
        Path("/tmp/agent-shutdown-debug.log").read_text()
        if Path("/tmp/agent-shutdown-debug.log").exists()
        else ""
    )
    _run_hook(wt, env)
    after = Path("/tmp/agent-shutdown-debug.log").read_text()
    new_lines = after[len(before) :]

    assert "calling unregister-by-path" in new_lines, (
        "Hook must accept single-quoted `project: 'beta'` and resolve via "
        "credentials.d/beta. Debug log delta:\n" + new_lines
    )


def test_hook_is_idempotent_across_multiple_firings(
    stub_worktree: tuple[Path, Path], tmp_path: Path
) -> None:
    """Close-wave may kill an agent after the agent already wrote its own
    event; the hook then fires and writes a second line. Both events must be
    valid JSON so the close-wave consumer can deduplicate on (worktree, ts)."""
    main, wt = stub_worktree
    env = {"HOME": str(tmp_path / "empty-home"), "PATH": os.environ["PATH"]}
    _run_hook(wt, env)
    _run_hook(wt, env)

    lines = (main / ".cloglog" / "inbox").read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        event = json.loads(line)
        assert event["type"] == "agent_unregistered"
        assert event["worktree"] == "wt-sim"
