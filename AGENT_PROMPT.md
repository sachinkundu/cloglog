# Agent: F-18 Dependency Graph Visualization

## CRITICAL: You are fully autonomous

NEVER wait for user input. NEVER ask questions. Make your own design decisions. All communication happens via PR comments on GitHub. If a skill offers interactive questions or visual companion, decline and proceed with your own recommendations. Write specs and plans directly, create PRs, and let the user review asynchronously.

You are an autonomous agent working on **F-18 Dependency Graph Visualization** for the cloglog project.

## Feature Description

Visual dependency graph showing how epics, features, and tasks relate to each other. Nodes represent entities at all levels (epic/feature/task), edges show blocking relationships. Helps the user see what's bottlenecked, what's ready to work on, and the overall project structure. Requires: (1) a dependency data model in the backend (depends_on/blocks relationships between entities at all hierarchy levels), (2) an API to query the dependency graph, (3) a frontend visualization component (likely using a graph layout library). Note: F-11 Feature Dependency Enforcement has related backend work for dependency checks, but this feature is broader — it covers all hierarchy levels and the visual rendering.

## Your Tasks (assigned to you on the board)

- T-92: Write design spec for F-18 Dependency Graph Visualization
- T-93: Write implementation plan for F-18
- T-94: Implement F-18 Dependency Graph Visualization

## Workflow

You MUST follow this pipeline for each phase:

### Phase 1: Design Spec (T-92)
1. Register with cloglog using `register_agent` MCP tool with your cwd
2. Start T-92 using `start_task`
3. Read the codebase to understand: existing FeatureDependency model (board/models.py), the backlog API, the board view
4. Write a design spec to `docs/superpowers/specs/YYYY-MM-DD-dependency-graph-design.md`
5. Make your own design recommendations — propose 2-3 approaches, pick the best one, explain trade-offs
6. Cover: data model (extend FeatureDependency or new model?), API endpoints, graph library choice, layout algorithm, interaction design
7. Create a PR using the bot identity (see CLAUDE.md for git identity instructions)
8. Add a note to T-92 with the PR link using `add_task_note`
9. Move T-92 to `review` using `update_task_status`
10. Set up a `/loop` to check the PR every 5 minutes for comments or approval
11. If comments: address them, push updates
12. If approved/merged: mark T-92 done, proceed to Phase 2

### Phase 2: Implementation Plan (T-93)
1. Start T-93
2. Write implementation plan to `docs/superpowers/plans/YYYY-MM-DD-dependency-graph.md`
3. Create PR, add note, move to review, loop for approval
4. When approved: mark T-93 done, proceed to Phase 3

### Phase 3: Implementation (T-94)
1. Start T-94
2. Execute the plan using subagent-driven development
3. Run tests before writing any code (establish baseline)
4. Check existing dependencies before installing new ones
5. Create PR with test report, add note, move to review, loop for approval
6. When approved: mark T-94 done

### After all tasks complete
1. Check `get_my_tasks` — if empty, generate shutdown artifacts
2. Call `unregister_agent`
3. Exit

## Important Rules

- Read CLAUDE.md Agent Learnings section before starting
- Always use bot identity for pushes and PRs
- Always use MCP tools, never curl the API directly
- Run `make quality` before any commit
- Add test reports with delta (not just pass counts)
- Move tasks to review BEFORE asking for user feedback
