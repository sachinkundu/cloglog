# F-23: Agent Proof-of-Work Demo Documents — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-04-06-f23-agent-proof-of-work-design.md`

## Overview

This plan implements the demo document system in 5 parallelizable work streams. The gateway worktree owns the scripts and Makefile changes; CLAUDE.md updates and `create-worktree.sh` changes touch shared files.

## Scope Constraint

This worktree is `wt-gateway` — restricted to `src/gateway/` and `tests/gateway/`. However, F-23 is primarily about scripts, Makefile, and CLAUDE.md — not gateway code. The implementation tasks that touch files outside `src/gateway/` and `tests/gateway/` will need to be done from the main branch or a non-context-restricted worktree.

**Recommendation:** Execute all tasks from a single worktree with unrestricted file access, or have the main agent execute directly on a feature branch.

## Implementation Tasks

### Task 1: `scripts/worktree-ports.sh` — Port Allocation

**Files:** `scripts/worktree-ports.sh` (new)

Create the port allocation script that derives deterministic ports from the worktree name.

```bash
#!/bin/bash
# Derives deterministic port assignments for the current worktree.
# Source this script to set BACKEND_PORT, FRONTEND_PORT, DB_PORT.

set -euo pipefail

WORKTREE_PATH="${WORKTREE_PATH:-$(git rev-parse --show-toplevel)}"
WORKTREE_NAME=$(basename "$WORKTREE_PATH")

# Hash worktree name to a base port in range 10000-60000
BASE_PORT=$(( ($(echo "$WORKTREE_NAME" | cksum | cut -d' ' -f1) % 50000) + 10000 ))

export BACKEND_PORT=$BASE_PORT
export FRONTEND_PORT=$((BASE_PORT + 1))
export DB_PORT=$((BASE_PORT + 2))
export WORKTREE_DB_NAME="cloglog_${WORKTREE_NAME//-/_}"
export DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/${WORKTREE_DB_NAME}"
```

**Test:** Source the script with different `WORKTREE_PATH` values and verify ports are deterministic and in range.

**Dependencies:** None — fully independent.

### Task 2: `scripts/worktree-infra.sh` — Infrastructure Setup/Teardown

**Files:** `scripts/worktree-infra.sh` (new)

Two subcommands: `up` (create DB, run migrations) and `down` (drop DB, kill port processes).

```
up:
  1. Source worktree-ports.sh
  2. Create DB if not exists
  3. Run alembic migrations against worktree DB
  4. Write .env file with port assignments

down:
  1. Source worktree-ports.sh
  2. Kill processes on BACKEND_PORT, FRONTEND_PORT
  3. Drop the worktree database
  4. Remove .env file
```

**Test:** Run `up`, verify DB exists and .env has correct ports. Run `down`, verify DB dropped and ports freed.

**Dependencies:** Task 1 (worktree-ports.sh).

### Task 3: `scripts/run-demo.sh` — Demo Orchestrator

**Files:** `scripts/run-demo.sh` (new)

The main orchestrator called by `make demo`:

1. Detect feature name from `DEMO_FEATURE` env var or branch name
2. Source worktree-ports.sh for port assignments
3. Run `scripts/worktree-infra.sh up`
4. Start backend on `$BACKEND_PORT` in background
5. If `docs/demos/<feature>/demo-script.sh` uses rodney commands, also start frontend on `$FRONTEND_PORT`
6. Wait for health checks (curl retry loop on `/health`)
7. Execute `docs/demos/<feature>/demo-script.sh`
8. Stop servers (kill background PIDs)
9. Exit with demo-script's exit code

**Key detail:** Does NOT call `worktree-infra.sh down` — infrastructure persists for the worktree lifetime. Teardown happens on worktree removal.

**Dependencies:** Task 1, Task 2.

### Task 4: `scripts/check-demo.sh` — Quality Gate Check

**Files:** `scripts/check-demo.sh` (new)

Called by `make demo-check` (integrated into `make quality`):

1. Detect feature from branch name or `DEMO_FEATURE`
2. If on `main` branch, skip silently (no demo needed on main)
3. Check `docs/demos/<feature>/demo.md` exists
4. If exists, run `showboat verify docs/demos/<feature>/demo.md` and check exit code
5. Exit 0 on success, non-zero with clear message on failure

**Edge case:** If `showboat` is not installed, print a warning but don't fail (first-time setup).

**Dependencies:** None — can be written independently.

### Task 5: Makefile Integration

**Files:** `Makefile`

Add two new targets:

```makefile
demo: ## Run proof-of-work demo for current feature
	@echo "Running proof-of-work demo..."
	@scripts/run-demo.sh

demo-check: ## Check demo document exists and verifies
	@scripts/check-demo.sh
```

Update the `quality` target to include `demo-check` after `contract-check`:

```
@echo "  Demo:"
@$(MAKE) --no-print-directory demo-check && echo "    verified           ✓" || (echo "    FAILED ✗" && exit 1)
```

**Dependencies:** Task 4 (check-demo.sh must exist).

### Task 6: `create-worktree.sh` Updates

**Files:** `scripts/create-worktree.sh`

Add to the worktree setup flow:

1. After creating the worktree, source `worktree-ports.sh` and run `worktree-infra.sh up`
2. Add demo and infrastructure sections to the generated CLAUDE.md template
3. Write `.env` with port assignments into the worktree directory

**Dependencies:** Task 1, Task 2.

### Task 7: `manage-worktrees.sh` Cleanup Hook

**Files:** `scripts/manage-worktrees.sh`

In the `remove` subcommand, before deleting the worktree directory:

1. Source `worktree-ports.sh` with the worktree path
2. Run `worktree-infra.sh down` to tear down infrastructure
3. Continue with existing worktree removal

**Dependencies:** Task 1, Task 2.

### Task 8: CLAUDE.md Agent Learnings Update

**Files:** `CLAUDE.md`

Add the "Proof-of-Work Demos" section to Agent Learnings as specified in the design spec.

**Dependencies:** None — can be done independently.

### Task 9: Tests

**Files:** `tests/` (shell script tests or pytest tests)

Write tests for:

1. **worktree-ports.sh:** Deterministic output, range validation, different worktree names produce different ports
2. **check-demo.sh:** Passes when demo.md exists, fails when missing, skips on main branch
3. **Integration:** `make demo-check` runs successfully when demo exists

Use `scripts/test-worktree-scripts.sh` as a pattern (it already exists for testing worktree scripts).

**Dependencies:** Tasks 1-5.

## Execution Order

```
Independent (parallel):
  ├── Task 1: worktree-ports.sh
  ├── Task 4: check-demo.sh  
  └── Task 8: CLAUDE.md update

After Task 1:
  └── Task 2: worktree-infra.sh

After Tasks 1+2:
  ├── Task 3: run-demo.sh
  ├── Task 6: create-worktree.sh updates
  └── Task 7: manage-worktrees.sh cleanup

After Tasks 3+4:
  └── Task 5: Makefile integration

After all:
  └── Task 9: Tests
```

## Worktree Constraint Resolution

Since this worktree (`wt-gateway`) is restricted to `src/gateway/` and `tests/gateway/`, but F-23's implementation is entirely in `scripts/`, `Makefile`, and `CLAUDE.md`:

**Option A (recommended):** The main agent executes this plan directly on a `f23-impl` branch from the main worktree, where there are no directory restrictions.

**Option B:** Create a new worktree with `scripts/` in its allowed directories.

This plan is ready for execution regardless of which option is chosen — the tasks and dependencies are the same.

## PR Checklist

- [ ] All scripts are executable (`chmod +x`)
- [ ] `make demo` works for a backend-only feature (curl-based demo)
- [ ] `make demo` works for a frontend feature (Rodney + Showboat)
- [ ] `make demo-check` passes when demo.md exists
- [ ] `make demo-check` fails with clear message when demo.md is missing
- [ ] `make quality` includes demo-check
- [ ] `create-worktree.sh` sets up isolated infrastructure
- [ ] `manage-worktrees.sh remove` tears down infrastructure
- [ ] Port allocation is deterministic and collision-free for known worktree names
- [ ] CLAUDE.md has Proof-of-Work Demos section in Agent Learnings
- [ ] Tests cover port allocation, demo check, and infrastructure lifecycle
