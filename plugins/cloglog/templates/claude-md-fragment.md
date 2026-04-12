## Cloglog Workflow Discipline

<!-- Injected by the cloglog plugin. These rules apply to all agents working on this project. -->

### Testing

- **Run all tests FIRST, before writing any code.** Establish a green baseline so you know any failures are caused by your changes, not pre-existing issues.
- **Every PR must include automated tests.** No exceptions. If you write code, you write tests for it.
- **Delegate test writing to the `test-writer` subagent.** It carries the codified testing standards. See `.claude/agents/test-writer.md`.
- **Cross-feature integration tests:** When modifying a component recently changed by another feature, write at least one test covering both features together. Check `git log --oneline <file>` to see recent changes.

### PR Quality

- **PR body structure:** Summary (1-3 bullets) → Demo (inline proof it works) → Test Report (delta, strategy, results).
- **The demo is the most important thing after the summary.** Embed output directly — curl responses, screenshots, state machine transitions. The reviewer should see proof before reading code.
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
  1. **"Write design spec for F-N"** — requires a PR. Move to `review` when spec PR is created. User reviews the spec.
  2. **"Write implementation plan for F-N"** — no PR needed. Write the plan, commit it, and immediately proceed to implementation. No separate approval needed.
  3. **"Implement F-N"** — requires a PR. Move to `review` when implementation PR is created. User reviews the code.
- Only spec and implementation need user review. The plan is an internal artifact.
- The board must reflect what is being worked on in real-time.

### Feature Pipeline Continuity

- **Create ALL three pipeline tasks upfront** when launching an agent for a feature. The state machine enforces ordering; having all tasks assigned means the agent knows its full workload and won't exit prematurely.
- **Agents must complete the full pipeline:** spec (PR, wait for merge) → plan (write and proceed) → impl (PR, wait for merge).
- **After each PR merges, call `get_my_tasks`.** If there are more tasks assigned, start the next one.
- **Never exit after just the spec task.** If `get_my_tasks` returns tasks, you have more work to do.

### Worktree Hygiene

- **Commit or stash all pending changes before creating worktrees.** Worktrees inherit uncommitted changes from the working tree — agents will see those diffs and mistakenly treat them as their own work.
- **Task lifecycle:** Move tasks through `in_progress → review` using the `update_task_status` MCP tool. Before moving to review, add a structured test report via `add_task_note` covering: (1) pre-existing tests, (2) modified tests, (3) new tests, (4) testing strategy, (5) results with clear delta. This demonstrates testing judgment, not just a pass count.
- **PR polling and CI recovery:** Use the `github-bot` skill — it has the exact commands and polling loop. When merged: for spec/plan tasks call `report_artifact`, then start the next task immediately.
- **Report artifacts after PR merge (enforced by state machine):** When a spec or plan PR merges, call `report_artifact` MCP tool with the repo-relative path to the document file. The pipeline guard blocks downstream tasks until the predecessor's artifact is attached. Only spec and plan tasks produce artifacts; impl and standalone tasks do not.

### Agent Shutdown

- **Agents deregister themselves.** When the feature pipeline is complete AND `get_my_tasks` returns empty, generate shutdown artifacts and unregister. Never rely on the main agent or scripts to deregister.
- **Do NOT exit prematurely.** Check `get_my_tasks` AND verify the full pipeline is complete before shutting down.
- **Three-tier shutdown:** (1) Cooperative — main agent requests shutdown, agent finishes current work and unregisters. (2) SIGTERM — if agent doesn't respond, send SIGTERM; SessionEnd hook unregisters best-effort. (3) Heartbeat timeout — stale sessions are cleaned up automatically.
- **Artifact handoff is explicit.** The unregister call includes paths to shutdown artifacts. The `WORKTREE_OFFLINE` event carries these paths for the main agent to consolidate.

### Proof-of-Work Demos

- **Every PR must include a `demo.md` that RUNS what you built, not describes it.** A demo is proof that your code works, not a summary of what you changed.
- **A demo is NOT:** test output, a list of files changed, a description of what was implemented, or grep of source code.
- **A demo IS:** executing the actual feature and showing the output. Think "if I were showing this to a colleague, what would I type in the terminal or click in the browser?"
- **Backend PRs:** Curl each new/changed endpoint. Show the request AND the response.
- **Frontend PRs:** Take a headless screenshot of the new/changed UI. Include before AND after if modifying existing UI.
- **State machine / guard PRs:** Show both the happy path (allowed transition) AND the rejection (blocked transition with error message).
- Demo scope: feature walkthrough only. Regression testing is handled by automated tests.

### Agent Communication

- **Agents communicate via inbox files.** Each agent has an inbox at `/tmp/cloglog-inbox-{worktree_id}`.
- **Receiving:** On registration, start a persistent Monitor on your inbox (`tail -f /tmp/cloglog-inbox-{your_worktree_id}`). Messages arrive as Monitor notifications in real-time.
- **Sending:** Append to the target agent's inbox: `echo "[sender] message" >> /tmp/cloglog-inbox-{target_id}`.
- **Inbox lifecycle:** Create the file on registration (`touch`), clean up on worktree removal (`rm`).
- **Main agent inbox:** The main session should also Monitor its own inbox so worktree agents can report back (e.g., "PR #N merged").

### Autonomous Agent Behavior

- **NEVER wait for user input.** Worktree agents are fully autonomous. All communication with the user happens via PR comments on GitHub — never via the terminal.
- **Never use interactive skills that ask questions.** Write design specs directly with your own recommendations, create the PR, and let the user review it there.
