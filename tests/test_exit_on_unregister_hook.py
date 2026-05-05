"""Pin tests: T-352, T-428, T-475.

After a successful `mcp__cloglog__unregister_agent` tool call, the
PostToolUse hook at `plugins/cloglog/hooks/exit-on-unregister.sh` MUST
schedule a TERM to its parent process (claude). Without this, the
launcher's `wait <claude_pid>` blocks forever after the agent
"exits" — claude keeps the session interactive even after the LLM has
no more turns to take, and the supervisor is forced to close the
zellij tab to teardown the worktree.

The reproducer drives the actual hook script with a synthetic parent
shell that echoes the PostToolUse JSON payload through the hook,
sleeps, and asserts the parent dies of SIGTERM within 10s. This
mirrors the live launcher → claude → hook process tree.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "plugins" / "cloglog" / "hooks" / "exit-on-unregister.sh"


def _payload(
    *,
    tool_name: str = "mcp__cloglog__unregister_agent",
    response_text: str = "Unregistered wt-foo.",
    is_error: bool = False,
) -> str:
    body: dict = {
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": {
            "content": [{"type": "text", "text": response_text}],
        },
    }
    if is_error:
        body["tool_response"]["isError"] = True
    return json.dumps(body)


def _run_with_fake_parent(payload: str, *, parent_sleep: int = 30) -> int:
    """Spawn a bash parent that runs the hook then sleeps.

    The hook's $PPID is this bash process. The hook backgrounds a watcher
    that TERMs $PPID after a short delay. We return the bash exit code
    so callers can assert SIGTERM (-15) vs natural exit (0).
    """
    if shutil.which("setsid") is None:
        pytest.skip("setsid required (Linux only)")
    # `exec ... < <(echo ...)` keeps the bash process the direct parent
    # of the hook (no subshell wrapping). bash receives TERM, sleep is
    # killed, bash exits with -SIGTERM.
    cmd = f"echo {json.dumps(payload)} | bash {HOOK}; sleep {parent_sleep}"
    proc = subprocess.Popen(["bash", "-c", cmd])
    try:
        return proc.wait(timeout=parent_sleep + 5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        proc.kill()
        proc.wait()
        raise


def test_successful_unregister_terminates_parent():
    """Happy path: hook sees success → parent dies of TERM within ~3s."""
    rc = _run_with_fake_parent(_payload(), parent_sleep=15)
    # bash on Linux exits 128+SIGNUM on signal death; Popen.wait returns
    # the negative signal value. Accept either form.
    assert rc in (-signal.SIGTERM, 128 + signal.SIGTERM), (
        f"parent should die of SIGTERM, got rc={rc}"
    )


def test_failed_unregister_leaves_parent_alone():
    """isError=true response → no TERM scheduled. Parent runs to natural exit."""
    rc = _run_with_fake_parent(
        _payload(response_text="Backend 500", is_error=True),
        parent_sleep=4,
    )
    assert rc == 0, f"parent must NOT be killed on tool error, got rc={rc}"


def test_unrelated_tool_call_is_noop():
    """Hook must only act on mcp__cloglog__unregister_agent."""
    rc = _run_with_fake_parent(
        _payload(tool_name="mcp__cloglog__start_task"),
        parent_sleep=4,
    )
    assert rc == 0, f"hook must ignore other tools, got rc={rc}"


def test_unexpected_response_shape_is_noop():
    """Defensive: text that does not start with 'Unregistered' → no kill."""
    rc = _run_with_fake_parent(
        _payload(response_text="Some other text"),
        parent_sleep=4,
    )
    assert rc == 0, f"hook must not kill on unexpected response, got rc={rc}"


def test_hook_is_wired_in_settings():
    """Pin the wiring — without the matcher entry the hook never fires."""
    settings = json.loads((REPO_ROOT / "plugins" / "cloglog" / "settings.json").read_text())
    matchers = [m.get("matcher") for m in settings["hooks"].get("PostToolUse", [])]
    assert "mcp__cloglog__unregister_agent" in matchers, (
        "exit-on-unregister hook is not wired into PostToolUse"
    )


# ---------------------------------------------------------------------------
# T-428: 5 deterministic recurrences on 2026-05-05 (close-wave work logs
# t394, t354, t437, t438) where the hook fired (debug log shows
# "exit-on-unregister.sh scheduled TERM ...") yet claude survived until tab
# force-close. Either the kill targeted a transient wrapper that exited
# before the kill landed, or claude's Node process trapped TERM with cleanup
# logic that did not exit. The fix:
#   1. launch.sh.template writes <worktree>/.cloglog/claude.pid, and
#   2. the hook prefers that file over $PPID and escalates TERM → INT → KILL.
# These pin tests reproduce both failure modes and assert the parent dies
# anyway. Bare existence checks (the original test below) cannot catch a
# parent that traps TERM — they would have passed all 5 recurrences.
# ---------------------------------------------------------------------------


def _run_signal_resistant_parent(
    payload: str,
    *,
    trap_signals: tuple[str, ...],
    parent_sleep: int = 30,
    pidfile: Path | None = None,
) -> int:
    """Spawn a bash parent that traps the given signals, then runs the hook.

    Simulates the real failure mode where claude's Node process catches
    TERM (and/or INT) and does not exit. The hook must escalate to KILL.

    If `pidfile` is provided, the parent writes its own PID there before
    invoking the hook — exercises the .cloglog/claude.pid lookup path.
    """
    if shutil.which("setsid") is None:
        pytest.skip("setsid required (Linux only)")
    traps = " ".join(f"trap '' {sig}" for sig in trap_signals)
    pidfile_setup = ""
    cwd_arg = ""
    if pidfile is not None:
        pidfile_setup = f"echo $$ > {pidfile}; "
        # cwd in input must be inside a git repo whose .cloglog/claude.pid
        # the hook will read. We pass the pidfile's parent's parent.
        worktree_root = pidfile.parent.parent
        cwd_arg = str(worktree_root)
    payload_with_cwd = payload
    if cwd_arg:
        body = json.loads(payload)
        body["cwd"] = cwd_arg
        payload_with_cwd = json.dumps(body)
    cmd = (
        f"{traps}; {pidfile_setup}"
        f"echo {json.dumps(payload_with_cwd)} | bash {HOOK}; sleep {parent_sleep}"
    )
    proc = subprocess.Popen(["bash", "-c", cmd])
    try:
        return proc.wait(timeout=parent_sleep + 5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise


def test_parent_trapping_term_is_escalated_to_kill():
    """T-428: a parent that ignores TERM must still die — escalation to
    INT, then KILL. Reproduces the 2026-05-05 failure mode where claude
    survived a single TERM."""
    rc = _run_signal_resistant_parent(
        _payload(),
        trap_signals=("TERM", "INT"),
        parent_sleep=20,
    )
    assert rc in (-signal.SIGKILL, 128 + signal.SIGKILL), (
        f"parent ignoring TERM/INT must die of SIGKILL, got rc={rc}. "
        "If this fails the hook is back to the 2026-05-05 single-TERM bug."
    )


def test_parent_trapping_term_only_dies_on_int():
    """T-428: parent traps TERM but not INT — escalation to INT must
    succeed before reaching KILL."""
    rc = _run_signal_resistant_parent(
        _payload(),
        trap_signals=("TERM",),
        parent_sleep=20,
    )
    # bash -c with `trap '' TERM` ignores TERM entirely; INT kills it.
    assert rc in (-signal.SIGINT, 128 + signal.SIGINT), (
        f"parent must die of SIGINT after TERM is trapped, got rc={rc}"
    )


def test_hook_prefers_pidfile_over_ppid(tmp_path):
    """T-428: when <worktree>/.cloglog/claude.pid exists and points at a
    live process, the hook targets it instead of $PPID. This is the
    authoritative-PID path the launcher.sh now writes — it survives
    spawn-time variance in how claude wraps the hook script."""
    if shutil.which("git") is None:
        pytest.skip("git required")
    # Build a real git worktree-ish layout so `git rev-parse --show-toplevel`
    # from cwd resolves to tmp_path/wt.
    wt = tmp_path / "wt"
    (wt / ".cloglog").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    pidfile = wt / ".cloglog" / "claude.pid"
    # Spawn a victim process whose only job is to sleep — the pidfile
    # points at IT, and we assert the victim dies (not the bash parent).
    victim = subprocess.Popen(["bash", "-c", "sleep 30"])
    pidfile.write_text(str(victim.pid))
    try:
        body = json.loads(_payload())
        body["cwd"] = str(wt)
        payload = json.dumps(body)
        # Run the hook from a parent that is NOT the victim. If the hook
        # used $PPID it would kill us; with pidfile it kills victim.
        cmd = f"echo {json.dumps(payload)} | bash {HOOK}; sleep 15"
        runner = subprocess.Popen(["bash", "-c", cmd])
        try:
            victim_rc = victim.wait(timeout=15)
        except subprocess.TimeoutExpired:
            runner.kill()
            victim.kill()
            raise AssertionError("hook did not target the pidfile PID") from None
        finally:
            runner.terminate()
            try:
                runner.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runner.kill()
        assert victim_rc in (-signal.SIGTERM, 128 + signal.SIGTERM), (
            f"victim (pidfile target) should die of SIGTERM, got rc={victim_rc}"
        )
    finally:
        if victim.poll() is None:
            victim.kill()
            victim.wait()


def test_launch_template_writes_pidfile():
    """T-428: pin the launcher-side half of the fix. Without this write,
    the hook falls back to $PPID and the 2026-05-05 bug recurs."""
    template = REPO_ROOT / "plugins" / "cloglog" / "templates" / "launch.sh.template"
    text = template.read_text()
    assert "claude.pid" in text, (
        "launch.sh.template must write <worktree>/.cloglog/claude.pid for "
        "the exit-on-unregister hook to target the right process (T-428)"
    )
    # Order: the write must come AFTER `CLAUDE_PID=$!` (we need the real
    # PID, not an empty var) and BEFORE `wait` (so the file exists for
    # the entire claude lifetime).
    pid_capture = text.index("CLAUDE_PID=$!")
    pid_write = text.index("claude.pid")
    wait_call = text.index('wait "$CLAUDE_PID"')
    assert pid_capture < pid_write < wait_call, (
        "claude.pid write must be ordered: CLAUDE_PID=$! < write < wait"
    )


# ---------------------------------------------------------------------------
# T-475: breadcrumb and tree-walk fallback.
#
# Root cause of 2026-05-05 regression: wt-t430/t432/t435 had the T-352 hook
# (no pidfile, just $PPID, no debug log). $PPID was a transient wrapper shell
# spawned by Claude Code; that wrapper exited before the setsid delay fired,
# so the killer saw "parent already gone" and quit — claude stayed alive.
#
# Two new invariants:
#   1. A breadcrumb is written to the debug log the moment the hook fires,
#      before any early-exit guard — so investigators can distinguish "hook
#      never ran" from "hook ran but conditions failed".
#   2. When no pidfile exists but an ancestor process has
#      --dangerously-skip-permissions in its args (launch.sh always passes
#      this to claude), the hook walks the process tree to find and kill
#      claude, rather than targeting $PPID (transient wrapper).
# ---------------------------------------------------------------------------


def test_breadcrumb_written_when_hook_fires(tmp_path):
    """T-475: debug log must contain an 'exit-on-unregister.sh fired' line
    the moment the hook runs, even when it exits early (e.g. IS_ERROR guard).
    Uses CLOGLOG_SHUTDOWN_LOG to avoid polluting /tmp/agent-shutdown-debug.log."""
    if shutil.which("setsid") is None:
        pytest.skip("setsid required (Linux only)")

    log = tmp_path / "shutdown-debug.log"
    env = {**os.environ, "CLOGLOG_SHUTDOWN_LOG": str(log)}

    # IS_ERROR=true triggers early exit — before the "scheduled" log line.
    payload = _payload(is_error=True)
    cmd = f"echo {json.dumps(payload)} | bash {HOOK}"
    subprocess.run(["bash", "-c", cmd], env=env, check=True)

    assert log.exists(), "hook must create the debug log"
    content = log.read_text()
    assert "exit-on-unregister.sh fired" in content, (
        "T-475: breadcrumb must appear in debug log even when IS_ERROR guard "
        "exits early. Without this, 'no log entries' is ambiguous: it could "
        "mean the hook never ran OR it ran but conditions failed."
    )
    assert "scheduled" not in content, (
        "IS_ERROR=true must NOT reach the 'scheduled' log line — breadcrumb only, no killer spawned"
    )


def test_hook_finds_claude_via_tree_walk(tmp_path):
    """T-475: when no pidfile and $PPID is a transient wrapper without
    --dangerously-skip-permissions, the hook must walk the process tree to
    find and kill the ancestor that has that flag (simulating claude).

    Process tree:
        victim  (bash victim.sh --dangerously-skip-permissions)
          wrapper  (bash -c 'echo PAYLOAD | bash HOOK')
            hook  ($PPID = wrapper; tree walk → victim at level ≤ 2)

    Expected: victim receives SIGTERM from the setsid escalating killer.
    The hook's $PPID (wrapper) has no --dangerously-skip-permissions flag,
    so the tree walk must look one level higher to find the victim.
    """
    if shutil.which("setsid") is None:
        pytest.skip("setsid required (Linux only)")

    log = tmp_path / "shutdown-debug.log"
    env = {**os.environ, "CLOGLOG_SHUTDOWN_LOG": str(log)}
    payload = _payload()

    # victim_script: run the hook as a child (wrapper), then sleep.
    # Invoked as "bash victim_script.sh --dangerously-skip-permissions" so
    # ps -o args= shows the flag — this is how the tree walk identifies claude.
    wrapper_cmd = f"echo {json.dumps(payload)} | bash {HOOK}"
    victim_script = tmp_path / "victim.sh"
    victim_script.write_text(
        textwrap.dedent(f"""\
            #!/bin/bash
            bash -c {json.dumps(wrapper_cmd)}
            sleep 60
        """)
    )
    victim_script.chmod(0o755)

    proc = subprocess.Popen(
        ["bash", str(victim_script), "--dangerously-skip-permissions"],
        env=env,
    )
    try:
        rc = proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(
            "victim did not exit within 25s — tree walk did not find claude ancestor "
            "(T-475: hook must walk process tree when no pidfile)"
        ) from None

    assert rc in (-signal.SIGTERM, 128 + signal.SIGTERM), (
        f"victim (ancestor with --dangerously-skip-permissions) must die of SIGTERM "
        f"via tree walk; got rc={rc}. "
        "If SIGKILL: escalation reached but TERM/INT were ignored — check target. "
        "If 0: victim exited naturally before the hook killed it."
    )

    # Bonus: verify the log shows tree-walk was used as the source
    if log.exists():
        content = log.read_text()
        assert "tree-walk" in content, (
            "debug log must record that tree-walk strategy was used "
            "(source=tree-walk-l<N> in 'scheduled' line)"
        )
