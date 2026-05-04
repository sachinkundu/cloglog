"""T-419 pin: inbox-monitor dedup must operate at the process level.

TaskList-based dedup is broken across sessions: persistent tail processes
survive `/clear` and become invisible orphans — TaskList sees zero matches
in the new session and spawns a duplicate tail.  Every subsequent setup adds
another, so inbox events fire N times where N is the number of setups ever run.

The fix is `plugins/cloglog/skills/setup/dedup-inbox-monitor.sh`, which uses
`ps` (host-wide process list) rather than the in-process task registry.

Pin tests verify:
1. One stale orphan → script kills it, exits 2 (caller spawns fresh Monitor).
2. Multiple duplicates → script kills all-but-oldest, exits 0 (one remains).
3. Cross-project safety: tails on a different inbox path are untouched.
4. Script is executable and referenced in SKILL.md.
5. Zero tails → script exits 2 (spawn fresh) without error.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "plugins/cloglog/skills/setup/dedup-inbox-monitor.sh"
SKILL_MD = REPO_ROOT / "plugins/cloglog/skills/setup/SKILL.md"


# ── helpers ───────────────────────────────────────────────────────────────


def _make_inbox(path: Path) -> Path:
    """Create .cloglog/inbox under path and return its absolute path."""
    inbox = path / ".cloglog" / "inbox"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.touch()
    return inbox


def _spawn_tail(inbox: Path) -> subprocess.Popen:
    """Start a persistent `tail -n 0 -F <inbox>` subprocess."""
    return subprocess.Popen(
        ["tail", "-n", "0", "-F", str(inbox)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _is_running(pid: int) -> bool:
    """Return True if the process is alive and not a zombie.

    os.kill(pid, 0) succeeds for zombie processes (terminated but not yet reaped
    by their parent).  A zombie tail is functionally dead — it no longer tails
    the file — so we must exclude zombies from the "still alive" check.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # On Linux, check /proc/<pid>/status for state "Z" (zombie).
    status_path = Path(f"/proc/{pid}/status")
    try:
        for line in status_path.read_text().splitlines():
            if line.startswith("State:"):
                return "Z" not in line
    except (FileNotFoundError, PermissionError):
        pass
    return True


def _run_dedup(inbox: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), str(inbox)],
        capture_output=True,
        text=True,
    )


def _count_tails(inbox: Path) -> int:
    """Count running tail processes watching exactly this inbox path."""
    result = subprocess.run(
        ["ps", "-ww", "-eo", "pid=,args="],
        capture_output=True,
        text=True,
    )
    pattern = f"-F {inbox}"
    count = 0
    for line in result.stdout.splitlines():
        if "tail" in line and line.endswith(pattern):
            count += 1
    return count


# ── script existence / permissions ───────────────────────────────────────


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT.exists(), f"{SCRIPT} missing"
    assert SCRIPT.stat().st_mode & 0o111, f"{SCRIPT} must be executable"


def test_skill_md_references_dedup_script() -> None:
    body = SKILL_MD.read_text(encoding="utf-8")
    assert "dedup-inbox-monitor.sh" in body, (
        "setup/SKILL.md must reference dedup-inbox-monitor.sh so operators "
        "and agents can locate the helper."
    )


def test_skill_md_does_not_instruct_calling_tasklist_for_dedup() -> None:
    """Step 2 must not instruct the agent to call TaskList as the dedup mechanism.

    The old dedup said '1. Call `TaskList`.' — that instruction is broken because
    TaskList is session-scoped and cannot see orphan tails from prior sessions.
    The fix replaces the TaskList call with the process-level dedup-inbox-monitor.sh.

    Note: Step 2 MAY still mention TaskList in explanatory prose (e.g. to say
    *why* TaskList-based dedup fails). The pin checks for the specific instruction
    pattern 'Call `TaskList`' that the old Step 2 contained.
    """
    body = SKILL_MD.read_text(encoding="utf-8")
    step2_start = body.find("### 2.")
    step3_start = body.find("### 3.", step2_start + 1) if step2_start != -1 else -1
    if step2_start != -1 and step3_start != -1:
        step2_body = body[step2_start:step3_start]
    elif step2_start != -1:
        step2_body = body[step2_start:]
    else:
        step2_body = ""
    # Check for the specific call-instruction pattern, not any mention of the word.
    assert "Call `TaskList`" not in step2_body and "1. Call `TaskList`" not in step2_body, (
        "setup/SKILL.md Step 2 must not instruct calling TaskList as the dedup mechanism. "
        "TaskList is session-scoped and cannot see cross-session orphan tails. "
        "Use dedup-inbox-monitor.sh (process-level ps scan) instead."
    )


# ── zero tails ────────────────────────────────────────────────────────────


def test_no_tails_exits_2(tmp_path: Path) -> None:
    """No running monitor → exit 2, caller must spawn fresh."""
    inbox = _make_inbox(tmp_path)
    result = _run_dedup(inbox)
    assert result.returncode == 2, (
        f"Expected exit 2 (no monitor, spawn fresh) but got {result.returncode}. "
        f"stderr: {result.stderr!r}"
    )


# ── one orphan tail ────────────────────────────────────────────────────────


def test_one_orphan_is_killed_and_exits_2(tmp_path: Path) -> None:
    """One stale orphan → script kills it and exits 2 (caller spawns fresh Monitor).

    The killed orphan had no Monitor task_id in the current session (it was
    started by a prior session).  Killing it and spawning fresh binds the new
    tail to this conversation's task registry so TaskStop works correctly.
    """
    inbox = _make_inbox(tmp_path)
    proc = _spawn_tail(inbox)
    try:
        # Give the tail a moment to start
        time.sleep(0.1)

        result = _run_dedup(inbox)

        assert result.returncode == 2, (
            f"Expected exit 2 (orphan killed, spawn fresh) but got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )
        # Wait briefly for kill to propagate
        time.sleep(0.1)
        assert not _is_running(proc.pid), (
            f"Orphan tail PID {proc.pid} must be killed by the dedup script. "
            "It survived — dedup did not send the kill signal."
        )
        assert _count_tails(inbox) == 0, (
            "After killing the orphan, no tail processes should remain on the inbox."
        )
    finally:
        if _is_running(proc.pid):
            proc.terminate()
        proc.wait()


def test_one_orphan_kill_message_on_stderr(tmp_path: Path) -> None:
    """Script must emit a diagnostic to stderr when killing an orphan."""
    inbox = _make_inbox(tmp_path)
    proc = _spawn_tail(inbox)
    try:
        time.sleep(0.1)
        result = _run_dedup(inbox)
        assert result.stderr != "", (
            "Script must write a diagnostic to stderr when killing an orphan tail. "
            "Silent kills make it hard to debug duplicate-monitor incidents."
        )
    finally:
        if _is_running(proc.pid):
            proc.terminate()
        proc.wait()


# ── multiple duplicate tails ───────────────────────────────────────────────


def test_multiple_dupes_all_killed_exits_2(tmp_path: Path) -> None:
    """Three duplicate tails → script kills ALL and exits 2 (caller spawns fresh).

    Keeping any orphan tail (the old exit-0 path) leaves the new session with no
    Monitor task, so webhook events never surface as notifications.  The correct
    behaviour is always kill all, always spawn fresh.
    """
    inbox = _make_inbox(tmp_path)
    procs = [_spawn_tail(inbox) for _ in range(3)]
    try:
        time.sleep(0.2)  # let all three start

        # Confirm three are running before dedup
        assert _count_tails(inbox) == 3, "Expected 3 tail processes before dedup"

        result = _run_dedup(inbox)

        assert result.returncode == 2, (
            f"Expected exit 2 (all killed, spawn fresh) but got {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )
        time.sleep(0.1)
        remaining = _count_tails(inbox)
        assert remaining == 0, (
            f"Expected 0 tail processes after dedup (all killed), got {remaining}. "
            "The script must kill ALL orphans when duplicates are found — keeping one "
            "would leave no Monitor task bound to the current session."
        )
    finally:
        for p in procs:
            if _is_running(p.pid):
                p.terminate()
            p.wait()


def test_multiple_dupes_stderr_mentions_killed_count(tmp_path: Path) -> None:
    """Script must report how many duplicates it killed."""
    inbox = _make_inbox(tmp_path)
    procs = [_spawn_tail(inbox) for _ in range(3)]
    try:
        time.sleep(0.2)
        result = _run_dedup(inbox)
        assert result.stderr != "", "Script must emit a diagnostic when killing duplicates."
        assert any(c in result.stderr for c in ("2", "duplicate", "Killed")), (
            "stderr should mention the number of killed duplicates or use 'Killed'/'duplicate'. "
            f"Got: {result.stderr!r}"
        )
    finally:
        for p in procs:
            if _is_running(p.pid):
                p.terminate()
            p.wait()


# ── cross-project safety ──────────────────────────────────────────────────


def test_cross_project_dedup_does_not_kill_other_inbox(tmp_path: Path) -> None:
    """Dedup against inbox A must NOT kill a tail on inbox B.

    Monitors from other projects running on the same host share the same ps
    output.  Without path anchoring, a naive pattern match on `.cloglog/inbox`
    would terminate unrelated supervisors.
    """
    inbox_a = _make_inbox(tmp_path / "project_a")
    inbox_b = _make_inbox(tmp_path / "project_b")

    proc_a = _spawn_tail(inbox_a)
    proc_b = _spawn_tail(inbox_b)
    try:
        time.sleep(0.1)

        # Dedup against inbox A only
        _run_dedup(inbox_a)

        time.sleep(0.1)
        assert _is_running(proc_b.pid), (
            f"Dedup against {inbox_a} must NOT kill the tail on {inbox_b}. "
            f"Cross-project safety: PID {proc_b.pid} (project_b) was terminated."
        )
        # inbox_b tail count must still be 1
        assert _count_tails(inbox_b) == 1, (
            f"After dedup against inbox_a, inbox_b should still have 1 tail. "
            f"Got {_count_tails(inbox_b)}."
        )
    finally:
        for p in (proc_a, proc_b):
            if _is_running(p.pid):
                p.terminate()
            p.wait()


def test_cross_project_dedup_kills_only_target_inbox(tmp_path: Path) -> None:
    """Multiple tails on inbox A plus one tail on inbox B: dedup on A kills
    ALL A-tails (exits 2) and leaves B untouched."""
    inbox_a = _make_inbox(tmp_path / "project_a")
    inbox_b = _make_inbox(tmp_path / "project_b")

    procs_a = [_spawn_tail(inbox_a) for _ in range(3)]
    proc_b = _spawn_tail(inbox_b)
    try:
        time.sleep(0.2)

        result = _run_dedup(inbox_a)

        time.sleep(0.1)
        assert _count_tails(inbox_a) == 0, (
            f"Dedup on inbox_a must kill all tails (spawn-fresh). Got {_count_tails(inbox_a)}."
        )
        assert _count_tails(inbox_b) == 1, (
            f"Dedup on inbox_a must not touch inbox_b. Got {_count_tails(inbox_b)}."
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (all A-tails killed, spawn fresh). Got {result.returncode}."
        )
    finally:
        for p in procs_a + [proc_b]:
            if _is_running(p.pid):
                p.terminate()
            p.wait()


# ── legacy relative-path form ─────────────────────────────────────────────


def _spawn_legacy_tail(inbox: Path) -> subprocess.Popen:
    """Spawn `tail -n 0 -F .cloglog/inbox` from the inbox's owning directory.

    This is the legacy form documented in setup/github-bot SKILLs.  The cwd
    is the project root (parent of .cloglog/), matching how the Monitor()
    helper was historically invoked.
    """
    cwd = inbox.parent.parent  # .../project_root  (parent of .cloglog/)
    return subprocess.Popen(
        ["tail", "-n", "0", "-F", ".cloglog/inbox"],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_legacy_relative_tail_is_detected_and_killed(tmp_path: Path) -> None:
    """A surviving `tail -n 0 -F .cloglog/inbox` orphan from a prior session
    must be detected and killed — not silently ignored.

    Before the T-419 fix, the canonical-form awk pattern ($NF == abs_path)
    did not match the relative-form process, so setup would take the '0 pids'
    branch and spawn a duplicate tail alongside the orphan.
    """
    inbox = _make_inbox(tmp_path)
    proc = _spawn_legacy_tail(inbox)
    try:
        time.sleep(0.1)
        result = _run_dedup(inbox)

        # Script must see the orphan (not take the zero-pids branch silently).
        # Either it killed it (exit 2) or it counts it as the one live monitor (exit 0).
        # Both are acceptable — what is NOT acceptable is exit 2 with the orphan still alive.
        time.sleep(0.1)
        if result.returncode == 2:
            # Orphan-killed-spawn-fresh path — process must be dead.
            assert not _is_running(proc.pid), (
                f"Script exited 2 (spawn-fresh) but legacy tail PID {proc.pid} "
                "is still alive. The legacy relative-path form was not detected."
            )
        else:
            # exit 0: script kept the orphan as the one live monitor — also valid.
            assert result.returncode == 0, (
                f"Unexpected exit code {result.returncode} from dedup script. "
                f"stderr: {result.stderr!r}"
            )
    finally:
        if _is_running(proc.pid):
            proc.terminate()
        proc.wait()


def test_legacy_form_from_different_cwd_is_not_matched(tmp_path: Path) -> None:
    """A `tail .cloglog/inbox` started from a DIFFERENT project root must NOT
    be treated as this project's monitor.

    Without the /proc/<pid>/cwd guard, a legacy tail from an unrelated checkout
    would satisfy the check for any project whose inbox dedup runs on the same host.
    """
    # Project A: the project we're deduping against
    inbox_a = _make_inbox(tmp_path / "project_a")
    # Project B: an unrelated checkout that happens to also run a legacy tail
    inbox_b = _make_inbox(tmp_path / "project_b")

    # Spawn a legacy tail from project_b's root
    proc_b_legacy = _spawn_legacy_tail(inbox_b)
    try:
        time.sleep(0.1)

        # Dedup against project_a — project_b's legacy tail must be untouched
        _run_dedup(inbox_a)

        time.sleep(0.1)
        assert _is_running(proc_b_legacy.pid), (
            f"Dedup against project_a killed a legacy tail (PID {proc_b_legacy.pid}) "
            "that belongs to project_b. The /proc cwd guard must prevent this."
        )
    finally:
        if _is_running(proc_b_legacy.pid):
            proc_b_legacy.terminate()
        proc_b_legacy.wait()


def test_legacy_and_canonical_mixed_deduplicates_to_one(tmp_path: Path) -> None:
    """One canonical tail + one legacy tail on the same inbox → dedup reduces to one."""
    inbox = _make_inbox(tmp_path)
    proc_canonical = _spawn_tail(inbox)  # absolute-path form
    proc_legacy = _spawn_legacy_tail(inbox)  # relative-path form
    try:
        time.sleep(0.2)

        _run_dedup(inbox)

        time.sleep(0.1)
        # All tails must be killed (script always exits 2, always spawns fresh).
        canonical_alive = _is_running(proc_canonical.pid)
        legacy_alive = _is_running(proc_legacy.pid)
        alive_count = sum([canonical_alive, legacy_alive])
        assert alive_count == 0, (
            f"Dedup of mixed canonical+legacy tails left {alive_count} processes alive "
            f"(canonical={canonical_alive}, legacy={legacy_alive}). "
            "Expected exactly 0 — keeping any orphan leaves no Monitor task in the new session."
        )
    finally:
        for p in (proc_canonical, proc_legacy):
            if _is_running(p.pid):
                p.terminate()
            p.wait()


# ── symlink checkout regression ───────────────────────────────────────────


def test_legacy_tail_from_symlinked_checkout_is_detected(tmp_path: Path) -> None:
    """A legacy tail started from a symlinked project root must be detected.

    Before the T-419 fix, EXPECTED_CWD was derived from the literal inbox
    argument string.  If setup was invoked with a canonical path but the
    legacy tail was started from a symlinked root (or vice-versa), the cwd
    comparison would fail and the orphan would be silently missed.

    The fix: EXPECTED_CWD is resolved with `pwd -P` (physical path), which
    matches what `readlink -f /proc/<pid>/cwd` and lsof return — both resolve
    symlinks before reporting the cwd.
    """
    real_root = tmp_path / "real_project"
    link_root = tmp_path / "link_project"
    real_root.mkdir()
    link_root.symlink_to(real_root)

    # Build the inbox under the real path
    real_inbox = _make_inbox(real_root)

    # Spawn a legacy tail from the SYMLINKED root — simulates a prior session
    # that was started via the symlink while the current session uses the real path.
    cwd = link_root  # symlink to real_root
    proc = subprocess.Popen(
        ["tail", "-n", "0", "-F", ".cloglog/inbox"],
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.1)

        # Run dedup against the canonical (real) inbox path
        result = _run_dedup(real_inbox)

        time.sleep(0.1)
        # The orphan must be detected and killed (exit 2 = spawn fresh)
        assert result.returncode == 2, (
            f"Dedup returned exit {result.returncode} but expected 2 (orphan killed). "
            "Legacy tail from symlinked root was not detected — EXPECTED_CWD must be "
            "resolved with pwd -P to match the physical cwd returned by /proc/<pid>/cwd."
        )
        assert not _is_running(proc.pid), (
            f"Legacy tail PID {proc.pid} (started from symlinked root) survived dedup. "
            "The symlink-aware EXPECTED_CWD fix (pwd -P) must resolve both paths to their "
            "physical equivalents before comparing."
        )
    finally:
        if _is_running(proc.pid):
            proc.terminate()
        proc.wait()
