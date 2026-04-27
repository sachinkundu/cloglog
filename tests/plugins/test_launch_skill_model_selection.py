"""Pin tests for T-332: per-task model selection in launch.sh.

The launch skill must:
1. Write the task's model to .cloglog/task-model before generating launch.sh.
2. The generated launch.sh reads that file at runtime and passes --model to claude.
3. The supervisor relaunch flow must update task-model before each continuation.
4. The claude invocation must use ${_MODEL_FLAG:+$_MODEL_FLAG} so missing model
   is a no-op (default model) rather than a crash.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LAUNCH_SKILL = REPO_ROOT / "plugins/cloglog/skills/launch/SKILL.md"


def _read(p: Path) -> str:
    assert p.exists(), f"{p} missing — fix the path or the file was moved"
    return p.read_text(encoding="utf-8")


def test_launch_skill_writes_task_model_file_before_launch_sh() -> None:
    """Step 4e must write .cloglog/task-model before generating launch.sh.

    The printf/write step must appear in the Step 4e block (before the cat
    heredoc) so the task-model file is in place when launch.sh first runs.
    """
    body = _read(LAUNCH_SKILL)

    # Extract Step 4e block — from "### 4e." up to the next "###" heading
    section_match = re.search(
        r"### 4e\..*?\n(.*?)(?=\n###|\Z)",
        body,
        flags=re.DOTALL,
    )
    assert section_match, "Step 4e section not found in launch SKILL.md"
    section = section_match.group(1)

    # The file write must appear before the `cat > ... << EOF` heredoc
    task_model_write_pos = section.find(".cloglog/task-model")
    cat_heredoc_pos = section.find("cat > ")
    assert task_model_write_pos != -1, (
        "Step 4e must write the task's model to .cloglog/task-model before "
        "generating launch.sh (T-332). Add: "
        'printf \'%s\\n\' "${TASK_MODEL:-}" > "${WORKTREE_PATH}/.cloglog/task-model"'
    )
    assert task_model_write_pos < cat_heredoc_pos, (
        ".cloglog/task-model write must appear BEFORE the `cat > launch.sh` heredoc "
        "in Step 4e — launch.sh reads the file on first run."
    )


def test_launch_sh_template_reads_task_model_file() -> None:
    """The launch.sh heredoc template must read .cloglog/task-model at runtime.

    This allows the supervisor to update the file before each continuation
    relaunch so the correct model is used for every task in the worktree.
    """
    body = _read(LAUNCH_SKILL)

    # The template must reference the task-model file
    assert ".cloglog/task-model" in body, (
        "launch.sh template must read the per-task model from "
        ".cloglog/task-model at runtime (T-332)."
    )

    # The template must set _MODEL_FLAG (the escaping form used in the heredoc)
    assert "_MODEL_FLAG" in body, (
        "launch.sh template must use _MODEL_FLAG to conditionally pass --model to claude (T-332)."
    )


def test_launch_sh_template_claude_invocation_uses_model_flag() -> None:
    """The claude invocation in launch.sh template must include the model flag.

    The form ${_MODEL_FLAG:+$_MODEL_FLAG} (after heredoc escape removal) means:
    - if _MODEL_FLAG is empty → nothing added (claude uses its default model)
    - if _MODEL_FLAG is set  → "--model <value>" is passed to claude
    """
    body = _read(LAUNCH_SKILL)

    # The heredoc source uses backslash-escaped vars; match either form
    # (the escaped form in SKILL.md or what it resolves to)
    assert re.search(r"claude --dangerously-skip-permissions.*_MODEL_FLAG", body), (
        "The claude invocation in the launch.sh heredoc must reference _MODEL_FLAG "
        "so the per-task model is passed as --model <value> (T-332). "
        "Expected: claude --dangerously-skip-permissions ${_MODEL_FLAG:+$_MODEL_FLAG} ..."
    )


def test_supervisor_relaunch_updates_task_model_before_relaunch() -> None:
    """The Supervisor Relaunch Flow must update .cloglog/task-model before relaunching.

    Without this, a continuation session would inherit the previous task's model
    rather than the next task's model, defeating per-task model selection.
    """
    body = _read(LAUNCH_SKILL)

    # Find the Supervisor Relaunch Flow section
    section_match = re.search(
        r"## Supervisor Relaunch Flow.*?(?=\n## |\Z)",
        body,
        flags=re.DOTALL,
    )
    assert section_match, "Supervisor Relaunch Flow section not found in launch SKILL.md"
    section = section_match.group(0)

    assert "task-model" in section, (
        "Supervisor Relaunch Flow must update .cloglog/task-model with the next "
        "task's model before calling launch.sh again (T-332). Without this, "
        "continuation relaunches use the wrong model."
    )

    # The task-model update must appear before the zellij write-chars command
    task_model_pos = section.find("task-model")
    write_chars_pos = section.find("write-chars")
    assert task_model_pos < write_chars_pos, (
        ".cloglog/task-model update must appear BEFORE zellij write-chars in the "
        "Supervisor Relaunch Flow — the file must be current before launch.sh runs."
    )
