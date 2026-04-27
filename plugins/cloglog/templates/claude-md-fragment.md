## Cloglog Workflow Discipline

<!-- Injected by the cloglog plugin. These rules apply to all agents working on this project. -->

### Testing

- **Run all tests FIRST, before writing any code.** Establish a green baseline so you know any failures are caused by your changes, not pre-existing issues.
- **Every PR must include automated tests.** No exceptions. If you write code, you write tests for it.
- **Delegate test writing to the `test-writer` subagent.** It carries the codified testing standards. See `.claude/agents/test-writer.md`.
- **Cross-feature integration tests:** When modifying a component recently changed by another feature, write at least one test covering both features together. Check `git log --oneline <file>` to see recent changes.

### PR Quality

- **PR body structure:** `## Demo` (stakeholder sentence + demo document link, OR exemption one-liner, OR static auto-exempt note) → `## Tests` (delta, strategy, results) → `## Changes` (what changed and why). Exactly these three sections, in this order — matches what `plugins/cloglog/skills/github-bot` and `plugins/cloglog/agents/worktree-agent.md` require, and what `plugins/cloglog/skills/demo` produces.
- **The demo is the most important section and comes first.** Embed output directly — curl responses, screenshots, state machine transitions. The reviewer should see proof before reading code.
- **Proactive rebase:** When other PRs merge to main while yours is open, rebase before the reviewer has to ask.
- **Conflict marker check:** After resolving merge conflicts, grep for `^<<<<<<` across source dirs to catch leftover markers.
- Run the full quality gate before pushing. Don't assume it passes.
- **One PR per task.** Wait for review and merge before starting the next task.

### Planning Before Implementation

- **Never create implementation tasks without going through the planning pipeline first.** The pipeline is: design spec → implementation plan → then create tasks and execute.
- Features on the board represent work to be planned, not pre-decomposed task lists. The implementation tasks emerge from the planning process.
- If you need to note a feature idea, create the feature on the board but leave it empty. The planning pipeline fills in the tasks.

### Execution Workflow (Mandatory)

- **Always use subagent-driven development** — never ask which execution approach; subagent-driven is always the choice.
- **Every phase of a feature needs a board task.** The full pipeline:
  1. **"Write design spec for F-N"** — requires a PR. Move to `review` when spec PR is created. User reviews the spec. After the PR merges, call `mark_pr_merged` then `report_artifact` with the spec file path.
  2. **"Write implementation plan for F-N"** — no PR needed. Write the plan, commit it locally. Then call `update_task_status(plan_task_id, "review", skip_pr=True)` followed by `report_artifact(plan_task_id, worktree_id, plan_path)`. No separate approval needed; proceed to implementation immediately after. **Known backend gap (T-NEW-b):** the pipeline guard at `src/agent/services.py:237` still requires `pr_url` on a `review`-status predecessor, so `start_task` on the impl returns 409 until T-NEW-b lands. A 409 is a runtime MCP tool error per §4.1 — when you hit it, emit `mcp_tool_error` with `reason: "pipeline_guard_blocked"` to the main inbox and stop. The supervisor recognises that reason and handles the advance. See `docs/design/agent-lifecycle.md` §1 for context and §4.1 for the event shape.
  3. **"Implement F-N"** — requires a PR. Move to `review` when implementation PR is created. User reviews the code.
- Only spec and implementation need user review. The plan is an internal artifact.
- The board must reflect what is being worked on in real-time.

### Feature Pipeline Continuity

- **Create ALL three pipeline tasks upfront** when launching an agent for a feature. The state machine enforces ordering; having all tasks assigned means the board reflects the full workload.
- **Agents execute one task per session (T-329).** When a task's PR merges, the agent writes a per-task work log (`shutdown-artifacts/work-log-T-<NNN>.md`), emits `agent_unregistered`, and exits. The supervisor relaunches in the same zellij tab for the next backlog task (if any) using the continuation prompt, or triggers close-wave if none remain. Do NOT call `get_my_tasks` after `pr_merged` to start the next task — the supervisor handles continuation.
- **Exception: plan → impl pipeline.** A plan task (no PR) immediately starts the following impl task in the same session. The session exits when the impl PR merges.
- **Standalone no-PR tasks also exit after completion.** A docs/research/prototype task that uses `skip_pr=True` (but is not a plan task) runs the per-task shutdown sequence with `reason: "no_pr_task_complete"` — skipping `mark_pr_merged` and `pr_merged_notification`. The supervisor then relaunches or triggers close-wave identically.

### Worktree Hygiene

- **Commit or stash all pending changes before creating worktrees.** Worktrees inherit uncommitted changes from the working tree — agents will see those diffs and mistakenly treat them as their own work.
- **Task lifecycle:** Move tasks through `in_progress → review` using the `update_task_status` MCP tool. Before moving to review, add a structured test report via `add_task_note` covering: (1) pre-existing tests, (2) modified tests, (3) new tests, (4) testing strategy, (5) results with clear delta. This demonstrates testing judgment, not just a pass count.
- **PR polling and CI recovery:** Use the `github-bot` skill — it has the exact commands and event responses. When merged: **first emit `pr_merged_notification` to `<project_root>/.cloglog/inbox`** (T-262), then call `mark_pr_merged`, then for spec/plan tasks call `report_artifact`, then write the per-task work log, emit `agent_unregistered`, call `unregister_agent`, and exit.
- **Report artifacts after PR merge (enforced by state machine):** When a spec or plan PR merges, call `report_artifact` MCP tool with the repo-relative path to the document file. The pipeline guard blocks downstream tasks until the predecessor's artifact is attached. Only spec and plan tasks produce artifacts; impl and standalone tasks do not.

### Agent Shutdown

- **Agents deregister themselves on `pr_merged` (T-329 — one task per session).** Exit condition: the `pr_merged` inbox event fires. Do NOT wait for empty `get_my_tasks` backlog — the supervisor handles relaunching for subsequent tasks.
- **Before `unregister_agent`, write `shutdown-artifacts/work-log-T-<NNN>.md`** (per-task work log) and emit an `agent_unregistered` event to `<project_root>/.cloglog/inbox` carrying `worktree`, `worktree_id`, `ts`, `tasks_completed`, the `prs` map (T-262 — `T-NNN -> PR URL`; build by walking `get_my_tasks()` for `pr_url`; omit tasks without a PR), and `reason: "pr_merged"`. The `artifacts.work_log` field must carry an absolute path to `shutdown-artifacts/work-log.md` (the aggregate of all per-task logs). The SessionEnd hook writes a best-effort fallback only.
- **Three-tier shutdown:** (1) Cooperative — main agent calls `request_shutdown`; agent finishes the current MCP call, runs the full shutdown sequence, unregisters. (2) Force unregister — main agent calls `force_unregister` (project-scoped admin tool); the backend unregisters unconditionally and the agent's next MCP call fails with auth rejection — a runtime tool error per §4.1, so the agent writes `mcp_tool_error` and waits (main initiated the force and can ignore the event). (3) Heartbeat timeout — server-side sweep at 180 s marks stale sessions offline; catch-all for crashes, not a cooperative signal.
- **Artifact handoff is explicit.** The `agent_unregistered` event carries absolute paths so the main agent can read them after the worktree is torn down.

### Proof-of-Work Demos

- **Every PR with user-observable behaviour change must include a `demo.md` that RUNS what you built, not describes it.** A demo is proof that your code works, not a summary of what you changed.
- **PRs without user-observable behaviour change — pure refactor, test-only, plugin/infra, dependency bumps — exempt through the `cloglog:demo` skill instead.** The skill runs two checks in order: Step 0 is a static allowlist short-circuit — when every changed file matches developer-infrastructure paths (`docs/`, `tests/`, `scripts/`, `.claude/`, `.cloglog/`, `.github/`, `Makefile`, `plugins/*/{hooks,skills,agents,templates}/`, `pyproject.toml`, `ruff.toml`, `package-lock.json`, `*.lock`), both the skill and `scripts/check-demo.sh` exit 0 with **no artifact written**. Step 1 invokes the `demo-classifier` subagent; when it returns `no_demo` the skill writes `docs/demos/<branch>/exemption.md` with a hash of the diff, which the gate accepts as a first-class artifact. Do not hand-write an "exemption declaration" paragraph in the PR body; the gate only recognises the committed `exemption.md` shape or the static auto-exempt path — never inline prose.
- **A demo is NOT:** test output, a list of files changed, a description of what was implemented, or grep of source code.
- **A demo IS:** executing the actual feature and showing the output. Think "if I were showing this to a colleague, what would I type in the terminal or click in the browser?"
- **Backend PRs:** Curl each new/changed endpoint. Show the request AND the response.
- **Frontend PRs:** Take a headless screenshot of the new/changed UI. Include before AND after if modifying existing UI.
- **State machine / guard PRs:** Show both the happy path (allowed transition) AND the rejection (blocked transition with error message).
- Demo scope: feature walkthrough only. Regression testing is handled by automated tests.

### Agent Communication

- **Agents communicate via inbox files.** Each agent has an inbox at `<worktree_path>/.cloglog/inbox` — the per-worktree file the webhook consumer and backend both write to. See `docs/design/agent-lifecycle.md` Section 3 for the inbox contract and a note on the removed legacy path.
- **Receiving:** On registration, start **exactly one** persistent Monitor on your inbox. Reconcile via `TaskList` first (match path suffix `/.cloglog/inbox`, reuse on one-match, keep-oldest on two+) — persistent monitors survive `/clear` and naive re-spawn duplicates the tail. Use `mkdir -p <worktree_path>/.cloglog && touch <worktree_path>/.cloglog/inbox && tail -n 0 -F <worktree_path>/.cloglog/inbox` (the `mkdir`/`touch` prelude is mandatory because the backend creates the inbox lazily on first webhook write; `-n 0` starts at end-of-file so the inbox's append-only history doesn't re-deliver already-handled events on a re-entered session; `-F` re-opens by name on rotation). To reconcile events that landed while offline, use the *Check PR Status* drill-down in the `github-bot` skill — never replay `tail` history. Messages arrive as Monitor notifications in real-time.
- **Sending:** Append to the target agent's inbox: `echo "[sender] message" >> <target_worktree_path>/.cloglog/inbox`. Look up the target path on the `worktrees` table — do not construct a path from a worktree id.
- **Inbox lifecycle:** The backend creates the inbox on first write (`mkdir -p` + append). On worktree removal, remove the `.cloglog/` directory.
- **Main agent inbox:** The main session runs its own Monitor on `<project_root>/.cloglog/inbox` so worktree agents can report back (e.g., `pr_merged`, `agent_unregistered`).

### Autonomous Agent Behavior

- **NEVER wait for user input.** Worktree agents are fully autonomous. All communication with the user happens via PR comments on GitHub — never via the terminal.
- **Never use interactive skills that ask questions.** Write design specs directly with your own recommendations, create the PR, and let the user review it there.

### Stop on MCP failure

- **Halt on any MCP failure: startup unavailability emits `mcp_unavailable` and exits; runtime tool errors emit `mcp_tool_error` and wait for the main agent; transient network errors get one backoff retry before escalating.** See `docs/design/agent-lifecycle.md` §4.1 for the full rule and both event shapes.
- **Startup unavailability** (ToolSearch returns no matches, or the first MCP call after register fails at the transport layer): write `mcp_unavailable` to `<project_root>/.cloglog/inbox` and exit. Do not fall back to direct HTTP, `gh api`, or the project API key — the agent cannot participate without MCP.
- **Runtime tool error** (HTTP 5xx, backend exception, 409 state-machine guard, schema-validation error): write `mcp_tool_error` to `<project_root>/.cloglog/inbox` carrying the failing tool name and error text, then **wait** on the inbox Monitor for main-agent guidance. A 409 is not advisory — it is the backend refusing the transition; silent continuation ships broken work.
- **Transient network errors** (`ECONNRESET`, `ETIMEDOUT`, fetch timeout): one retry after a short backoff (≥ 2 s). If the retry also fails, emit `mcp_tool_error` and wait. HTTP 5xx and 409 are NOT transient and MUST NOT be retried.
