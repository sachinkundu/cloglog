"""Pin test: T-352.

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
import shutil
import signal
import subprocess
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
