# F-23: Agent Proof-of-Work Demo Documents — Design Spec

## Problem

Agents produce frontend PRs with unit/integration test reports, but there's no proof the UI actually works in a real browser. Tests pass in jsdom while the rendered app may be broken. Reviewers have no way to verify visual correctness without manually running the app.

## Solution

After completing frontend work, agents use **Rodney** (headless Chrome CLI) and **Showboat** (executable document builder) to produce a reproducible demo document that proves the feature works. The demo is committed to the PR branch and summarized in the PR description.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| When to produce demo | Post-implementation, before PR | Keeps implementation loop fast; demo is a verification step |
| What to demo | Feature walkthrough only | Regression testing is handled by E2E suite (F-22) |
| How to deliver | Committed to branch + PR comment | Committed = reproducible via `showboat verify`; PR comment = easy review; both = historical record |
| Enforcement | `make demo` target + `make quality` check | Scriptable, testable, works for any developer, integrated into existing gate |

## Architecture

### Tools

- **Rodney** (`uvx rodney`): Headless Chrome automation via CLI. Start browser, navigate, click, type, screenshot, assert — all shell commands.
- **Showboat** (`uvx showboat`): Builds executable markdown documents from sequential CLI commands. Supports `verify` to re-run and diff all outputs.

Both are installed on-demand via `uvx` (no permanent dependency). Agents access them through shell commands.

### Demo Workflow

```
Agent completes implementation
        │
        ▼
   make demo
        │
        ├── 1. Start backend (make run-backend)
        ├── 2. Start frontend (cd frontend && npm run dev)
        ├── 3. Wait for servers to be ready
        ├── 4. rodney start (headless Chrome)
        ├── 5. showboat init docs/demos/<feature>.md "<Feature Title>"
        │
        ├── 6. For each key state of the feature:
        │      ├── rodney open <url>
        │      ├── rodney wait / rodney waitstable
        │      ├── rodney screenshot <file>.png
        │      ├── showboat note <file> "<explanation>"
        │      ├── showboat image <file> <screenshot>.png
        │      └── rodney assert / rodney text / rodney exists (verification)
        │
        ├── 7. showboat verify docs/demos/<feature>.md
        ├── 8. rodney stop
        ├── 9. Stop dev servers
        │
        └── 10. Commit demo doc + screenshots
```

### Directory Structure

```
docs/demos/
├── f22-e2e-test-suite/
│   ├── README.md          ← Showboat document
│   ├── 001-board-view.png
│   ├── 002-task-detail.png
│   └── ...
├── f23-proof-of-work/
│   ├── README.md
│   └── ...
```

Each feature gets its own subdirectory under `docs/demos/`. The Showboat document is `README.md` so it renders on GitHub. Screenshots are stored alongside it.

### `make demo` Target

A new Makefile target that orchestrates the full demo workflow:

```makefile
demo:
	@echo "Running proof-of-work demo..."
	@scripts/run-demo.sh
```

The `scripts/run-demo.sh` script:

1. **Detects which feature is being demoed** — reads from a `DEMO_FEATURE` env var or the current branch name (e.g., `wt-frontend` → looks for feature context)
2. **Starts servers** — backend and frontend in background, waits for health checks
3. **Runs the demo script** — executes `docs/demos/<feature>/demo-script.sh` if it exists (agent-authored), otherwise runs a default smoke test
4. **Cleans up** — stops servers, stops Rodney

### Demo Script (Agent-Authored)

Each feature's demo is driven by a shell script that the agent writes as part of its implementation:

```bash
#!/bin/bash
# docs/demos/f23-proof-of-work/demo-script.sh
# Agent writes this to demonstrate the feature

DEMO_FILE="docs/demos/f23-proof-of-work/README.md"

showboat init "$DEMO_FILE" "F-23: Agent Proof-of-Work Demo Documents"

showboat note "$DEMO_FILE" "Navigate to the board view and verify it loads correctly."

rodney open http://localhost:5173/projects
rodney waitstable
rodney screenshot docs/demos/f23-proof-of-work/001-board-view.png
showboat image "$DEMO_FILE" '![Board view loads correctly](001-board-view.png)'

# ... more steps ...

showboat verify "$DEMO_FILE"
```

### Quality Gate Integration

The `make quality` target is extended to check for demo documents on frontend PRs:

```makefile
quality: lint typecheck test coverage contract-check demo-check

demo-check:
	@scripts/check-demo.sh
```

`scripts/check-demo.sh`:
- Detects if the current branch has frontend changes (`git diff main --name-only | grep '^frontend/'`)
- If yes, checks that `docs/demos/` contains a demo document for this branch
- If no frontend changes, skip silently
- Exits non-zero with a clear message if demo is missing

This means:
- Backend-only PRs: no demo required
- Frontend PRs: demo required, enforced by quality gate
- The existing pre-commit hook (`quality-gate-before-commit.sh`) already runs `make quality`, so this is automatically enforced

### PR Integration

After the demo is committed, the agent includes it in the PR:

**PR body includes:**
```markdown
## Demo

A proof-of-work demo document is at [`docs/demos/<feature>/README.md`](link).

To re-verify: `showboat verify docs/demos/<feature>/README.md`

### Screenshots

![Board view](docs/demos/<feature>/001-board-view.png)
![Feature detail](docs/demos/<feature>/002-feature-detail.png)
```

The screenshots are embedded directly in the PR body so reviewers see them without navigating to files.

### CLAUDE.md Updates

Add to Agent Learnings section:

```markdown
### Proof-of-Work Demos
- **Every frontend PR must include a demo document.** After implementation, run `make demo` to produce it.
- The demo uses Rodney (headless Chrome) and Showboat (executable docs). Both are available via `uvx`.
- Write a `demo-script.sh` in your feature's `docs/demos/<feature>/` directory.
- The demo script should navigate to affected pages, capture screenshots, and run assertions.
- Demo documents are committed to the branch and summarized in the PR description.
- `make quality` will fail if a frontend PR is missing its demo.
- Demo scope: feature walkthrough only. Regression testing is handled by E2E tests.
```

## Agent Workflow Integration

### For Worktree Agents (Frontend)

The agent's implementation phase gains a new final step:

1. Write code
2. Write tests
3. Run tests
4. **Write demo-script.sh**
5. **Run `make demo`**
6. Commit everything (code + tests + demo)
7. Push and create PR (with demo screenshots in PR body)

### For the `create-worktree.sh` Script

Frontend worktree CLAUDE.md templates should include demo instructions. Add after the testing section:

```
## Demo

After implementation, write a demo script and run `make demo`.
See the Proof-of-Work Demos section in the root CLAUDE.md for details.
```

## Dependencies

- **Rodney**: `uvx rodney` (Go binary, distributed via PyPI)
- **Showboat**: `uvx showboat` (Go binary, distributed via PyPI)
- Both are ephemeral (`uvx` downloads on first use, cached afterward)
- No changes to `pyproject.toml` or `package.json`
- Requires Chrome/Chromium installed on the agent VM (already available)

## Edge Cases

- **No Chrome available**: `rodney start` fails with a clear error. Agent should note this in PR and skip demo. `check-demo.sh` can have a `--skip-if-no-chrome` flag.
- **Server startup failure**: `run-demo.sh` health-checks both servers with timeout. Fails clearly if either doesn't start.
- **Flaky screenshots**: Rodney's `waitstable` command waits for DOM to stop changing. Use it before every screenshot.
- **Large screenshots**: PNG files can be large. Use `rodney screenshot -w 1280 -h 720` for consistent viewport size and reasonable file sizes.
- **Demo verification drift**: If code changes after demo, `showboat verify` will catch it. Agent should re-run `make demo` before final push.

## What This Does NOT Cover

- **Visual regression testing** (F-24) — screenshot diffing across PRs
- **E2E regression tests** (F-22) — Playwright test suite for all routes
- **Accessibility audits** (F-25) — a11y checks via Rodney or Playwright
- **Backend-only proof of work** — this feature is frontend-focused

## Success Criteria

1. Frontend PRs include a `docs/demos/<feature>/README.md` with screenshots
2. `showboat verify` can re-run the demo and confirm outputs match
3. `make quality` fails if a frontend PR is missing its demo
4. PR description includes embedded screenshots for easy review
5. Agents can produce demos autonomously with no human intervention
