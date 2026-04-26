"""Regression guard: T-262.

Two protocol changes pinned by docs/skills (the agent's behaviour itself
is the LLM's responsibility, but the prompt template + lifecycle spec
MUST instruct it correctly):

1. On `pr_merged`, the agent emits a `pr_merged_notification` to the main
   inbox before calling `mark_pr_merged`. This surfaces the merge to the
   supervisor — the `pr_merged` webhook only fans out to the merging
   worktree's own inbox, so without this step a parallel worktree blocked
   on the PR has no signal short of polling `gh pr list`.

2. The `agent_unregistered` event carries a `prs` map (T-NNN -> PR URL)
   alongside the existing flat `tasks_completed` list. Option A (parallel
   map) was chosen so existing parsers keep working unchanged.

See `docs/design/agent-lifecycle.md` §1 (Trigger A), §2 step 5, §6
(outbound events) for the spec, and the launch SKILL prompt template
for the agent-side instructions.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE = REPO_ROOT / "docs" / "design" / "agent-lifecycle.md"
LAUNCH_SKILL = REPO_ROOT / "plugins" / "cloglog" / "skills" / "launch" / "SKILL.md"
GITHUB_BOT_SKILL = REPO_ROOT / "plugins" / "cloglog" / "skills" / "github-bot" / "SKILL.md"
CLAUDE_MD_FRAGMENT = REPO_ROOT / "plugins" / "cloglog" / "templates" / "claude-md-fragment.md"
WORKTREE_AGENT = REPO_ROOT / "plugins" / "cloglog" / "agents" / "worktree-agent.md"


def test_lifecycle_spec_documents_pr_merged_notification() -> None:
    spec = LIFECYCLE.read_text()
    # §6 outbound events table must list the new event type.
    assert "`pr_merged_notification`" in spec, (
        "agent-lifecycle.md §6 must document pr_merged_notification as an outbound event (T-262)"
    )
    # §1 algorithm must call out the emit BEFORE mark_pr_merged so a
    # supervisor reading the algorithm sees the order without crawling §6.
    assert "emit pr_merged_notification" in spec, (
        "agent-lifecycle.md §1 Trigger A must explicitly instruct the "
        "agent to emit pr_merged_notification before mark_pr_merged"
    )


def test_lifecycle_spec_documents_prs_map_in_unregister() -> None:
    spec = LIFECYCLE.read_text()
    # The example shape in §2 step 5 must include the prs key so agents
    # have a concrete template to copy.
    assert '"prs"' in spec, "agent-lifecycle.md §2 example must show the prs key"
    assert "Option A" in spec, (
        "agent-lifecycle.md must justify the prs shape (parallel map vs "
        "nested) so future maintainers know why tasks_completed stayed flat"
    )


def test_launch_skill_prompts_pr_merged_notification() -> None:
    prompt = LAUNCH_SKILL.read_text()
    assert "pr_merged_notification" in prompt, (
        "launch SKILL prompt template must instruct the agent to emit "
        "pr_merged_notification on pr_merged (T-262)"
    )


def test_launch_skill_prompts_prs_map_in_unregister() -> None:
    prompt = LAUNCH_SKILL.read_text()
    # The agent_unregistered example must carry a prs key so the agent
    # has a copy-paste template.
    assert '"prs"' in prompt, (
        "launch SKILL prompt template's agent_unregistered example must include the prs map (T-262)"
    )
    # And the build instruction (walk get_my_tasks for pr_url) must be
    # present so the agent knows where the data comes from.
    assert "get_my_tasks" in prompt and "pr_url" in prompt, (
        "launch SKILL must tell the agent to build the prs map from get_my_tasks rows' pr_url field"
    )


def test_task_info_exposes_fields_needed_for_prs_map():
    """T-262 round 2 (Codex): the documented `prs`-map construction path
    walks `get_my_tasks()` and reads each row's `pr_url` and task number
    (T-NNN). If TaskInfo doesn't expose those fields the protocol is
    impossible for agents to follow — pin the shape so any future
    schema slim-down has to remove the docs in lockstep.
    """
    from src.agent.schemas import TaskInfo

    fields = set(TaskInfo.model_fields.keys())
    assert "pr_url" in fields, (
        "TaskInfo must expose pr_url so agents can build the prs map at shutdown (T-262)"
    )
    assert "number" in fields, (
        "TaskInfo must expose number (the T-NNN suffix) so the prs map "
        "can be keyed by task ID (T-262)"
    )


def test_secondary_instruction_sources_propagate_t262():
    """The launch SKILL is not the only instruction source agents read.

    Codex flagged in PR #220 round 1 that github-bot SKILL, the
    claude-md-fragment template, and the worktree-agent agent definition
    all describe the pr_merged + shutdown protocol independently — and
    all of them must mention the new event/field or a launched agent
    following the referenced instructions can still recreate the
    visibility gap T-262 closes.
    """
    for path in (GITHUB_BOT_SKILL, CLAUDE_MD_FRAGMENT, WORKTREE_AGENT):
        body = path.read_text()
        assert "pr_merged_notification" in body, (
            f"{path.relative_to(REPO_ROOT)} must instruct agents to emit "
            "pr_merged_notification before mark_pr_merged (T-262)"
        )
        assert "prs" in body, (
            f"{path.relative_to(REPO_ROOT)} must mention the prs map "
            "in the agent_unregistered shape (T-262)"
        )
