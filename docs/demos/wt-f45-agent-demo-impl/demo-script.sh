#!/usr/bin/env bash
# Demo: T-184 — Agent Demo Skill (proof-of-work tooling for agents)
# Called by make demo (server + DB already running).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

DEMO_FILE="docs/demos/wt-f45-agent-demo-impl/demo.md"

uvx showboat init "$DEMO_FILE" "Agents now have a structured proof-of-work demo skill that enforces demo documents in every PR, with make quality blocking commits when demos are missing."

# Task 0: run-demo.sh fix
uvx showboat note "$DEMO_FILE" "Task 0: run-demo.sh now falls back to full branch name for worktree branches"
cat > /tmp/show-task0.sh << 'SHOW'
#!/usr/bin/env bash
grep -A4 "Fall back to" scripts/run-demo.sh
SHOW
chmod +x /tmp/show-task0.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task0.sh

# Task 1: demo skill
uvx showboat note "$DEMO_FILE" "Task 1: demo skill created at plugins/cloglog/skills/demo/SKILL.md"
cat > /tmp/show-task1.sh << 'SHOW'
#!/usr/bin/env bash
head -5 plugins/cloglog/skills/demo/SKILL.md
SHOW
chmod +x /tmp/show-task1.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task1.sh

# Task 2: quality gate
uvx showboat note "$DEMO_FILE" "Task 2: make quality now includes demo-check as the last step before PASSED"
cat > /tmp/show-task2.sh << 'SHOW'
#!/usr/bin/env bash
sed -n '/Demo:/,/Quality gate: PASSED/p' Makefile | head -6
SHOW
chmod +x /tmp/show-task2.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task2.sh

# Task 3: worktree-agent checkpoint
uvx showboat note "$DEMO_FILE" "Task 3: worktree-agent.md has explicit demo skill invocation checkpoint before PR"
cat > /tmp/show-task3.sh << 'SHOW'
#!/usr/bin/env bash
grep -A2 "invoke the demo skill" plugins/cloglog/agents/worktree-agent.md | head -4
SHOW
chmod +x /tmp/show-task3.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task3.sh

# Task 5: demo-reviewer agent
uvx showboat note "$DEMO_FILE" "Task 5: demo-reviewer subagent definition at .claude/agents/demo-reviewer.md"
cat > /tmp/show-task5.sh << 'SHOW'
#!/usr/bin/env bash
head -5 .claude/agents/demo-reviewer.md
SHOW
chmod +x /tmp/show-task5.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task5.sh

# Task 6: github-bot PR template
uvx showboat note "$DEMO_FILE" "Task 6: github-bot PR template now has ## Demo / ## Tests / ## Changes ordering"
cat > /tmp/show-task6.sh << 'SHOW'
#!/usr/bin/env bash
sed -n '/gh pr create/,/EOF/p' plugins/cloglog/skills/github-bot/SKILL.md | head -12
SHOW
chmod +x /tmp/show-task6.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-task6.sh

# Quality gate enforcement — show demo-check is wired into make quality (non-recursive check)
uvx showboat note "$DEMO_FILE" "demo-check is wired into make quality as the last enforcement step"
cat > /tmp/show-democheck.sh << 'SHOW'
#!/usr/bin/env bash
# Show demo-check step in quality target (proves enforcement without recursive verify)
grep -A2 "Demo:" Makefile | head -4
SHOW
chmod +x /tmp/show-democheck.sh
uvx showboat exec "$DEMO_FILE" /tmp/show-democheck.sh

uvx showboat verify "$DEMO_FILE"
