# Dev/Prod Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a stable gunicorn-based prod server on port 8001 from an isolated git worktree, keeping dev's hot-reload on port 8000, with `make promote` for zero-downtime deploys.

**Architecture:** Prod lives in a separate git worktree (`../cloglog-prod`) that only ever contains committed `origin/main` code. Gunicorn's SIGHUP rotates workers atomically so no webhook deliveries are dropped during `make promote`. Dev keeps hot-reload; the Cloudflare tunnel switches to port 8001.

**Tech Stack:** gunicorn, uvicorn.workers.UvicornWorker, git worktrees, Makefile

**Spec:** `docs/superpowers/specs/2026-04-18-dev-prod-separation-design.md`

---

## File Map

| File | Change |
|------|--------|
| `pyproject.toml` | Add `gunicorn>=23.0.0` dependency |
| `Makefile` | Add `prod`, `prod-bg`, `promote`, `prod-logs`, `prod-stop`; harden `dev` reload-exclude |
| `.cloglog/config.yaml` | Add `prod_worktree_path`, change `backend_url` to port 8001 |
| `plugins/cloglog/skills/close-wave/SKILL.md` | Step 1: filter worktrees to `.claude/worktrees/` path only |
| `mcp-server/src/index.ts` | Change default `CLOGLOG_URL` from port 8000 to 8001 |
| `~/.cloudflared/config.yml` | Change ingress target from 8000 to 8001 (manual step — not committed) |

---

## Task 1: Add gunicorn dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add gunicorn to dependencies**

In `pyproject.toml`, add gunicorn to the `dependencies` list alongside uvicorn:

```toml
dependencies = [
    ...
    "uvicorn[standard]>=0.32.0",
    "gunicorn>=23.0.0",
    ...
]
```

- [ ] **Step 2: Sync and verify**

```bash
uv sync
uv run gunicorn --version
```

Expected output: `gunicorn (version 23.x.x)`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add gunicorn for prod server"
```

---

## Task 2: Update Makefile — prod targets and dev hardening

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add prod targets after the `run-backend` target**

Find the `run-backend` target (line ~103) and add the following block immediately after:

```makefile
prod: ## Start prod server (gunicorn, port 8001, foreground — run in a zellij pane)
	@echo "Starting cloglog prod server on :8001..."
	@cd ../cloglog-prod && \
	  uv run gunicorn src.gateway.app:create_app \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers 2 \
	    --bind 0.0.0.0:8001 \
	    --pid /tmp/cloglog-prod.pid \
	    --error-logfile /tmp/cloglog-prod.log \
	    --access-logfile /tmp/cloglog-prod-access.log \
	    --log-level info \
	    --factory

prod-bg: ## Start prod server in background
	@echo "Starting cloglog prod server on :8001 (background)..."
	@cd ../cloglog-prod && \
	  uv run gunicorn src.gateway.app:create_app \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers 2 \
	    --bind 0.0.0.0:8001 \
	    --pid /tmp/cloglog-prod.pid \
	    --error-logfile /tmp/cloglog-prod.log \
	    --access-logfile /tmp/cloglog-prod-access.log \
	    --log-level info \
	    --factory \
	    --daemon
	@echo "  Prod server started. PID: $$(cat /tmp/cloglog-prod.pid)"

promote: ## Deploy latest origin/main to prod with zero-downtime worker rotation
	@echo "Promoting origin/main to prod..."
	@git -C ../cloglog-prod pull origin main
	@cd ../cloglog-prod && uv sync
	@cd ../cloglog-prod && uv run alembic upgrade head
	@kill -HUP $$(cat /tmp/cloglog-prod.pid)
	@echo "  Done — new workers loading from origin/main."

prod-logs: ## Tail prod server logs
	@tail -f /tmp/cloglog-prod.log /tmp/cloglog-prod-access.log

prod-stop: ## Stop the prod server
	@kill $$(cat /tmp/cloglog-prod.pid) && rm -f /tmp/cloglog-prod.pid && echo "Prod server stopped."
```

- [ ] **Step 2: Harden dev reload-exclude**

Replace the `dev` target's uvicorn line (line ~99) to exclude more paths:

```makefile
		uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
			--reload-exclude '.claude/worktrees' \
			--reload-exclude '__pycache__' \
			--reload-exclude '*.pyc' & \
```

Also update `run-backend` the same way:

```makefile
run-backend: ## Start the FastAPI backend
	uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
		--reload-exclude '.claude/worktrees' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc'
```

- [ ] **Step 3: Verify make help renders correctly**

```bash
make help 2>/dev/null || make
```

Check that `prod`, `promote`, `prod-logs`, `prod-stop` appear in the output.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat: add make prod/promote/prod-logs/prod-stop targets"
```

---

## Task 3: Update .cloglog/config.yaml

**Files:**
- Modify: `.cloglog/config.yaml`

- [ ] **Step 1: Add prod_worktree_path and update backend_url**

Current file:
```yaml
project: cloglog
project_id: 4d9e825a-c911-4110-bcd5-9072d1887813
backend_url: http://localhost:8000
quality_command: make quality

worktree_scopes:
  ...
```

Updated file — change `backend_url` to 8001 and add `prod_worktree_path`:

```yaml
project: cloglog
project_id: 4d9e825a-c911-4110-bcd5-9072d1887813
backend_url: http://localhost:8001
prod_worktree_path: ../cloglog-prod
quality_command: make quality

worktree_scopes:
  ...
```

Leave all `worktree_scopes` entries unchanged.

- [ ] **Step 2: Commit**

```bash
git add .cloglog/config.yaml
git commit -m "config: point backend_url to prod port 8001, add prod_worktree_path"
```

---

## Task 4: Update close-wave skill — path filter

**Files:**
- Modify: `plugins/cloglog/skills/close-wave/SKILL.md`

- [ ] **Step 1: Replace Step 1 in the skill**

Find the current Step 1 text:

```markdown
1. Run `git worktree list` to find active worktrees (anything beyond the main worktree)
```

Replace it with:

```markdown
1. Run `git worktree list --porcelain` to find active worktrees. **Filter to only worktrees whose path starts with `$(git rev-parse --show-toplevel)/.claude/worktrees/`.** Skip the main worktree and any worktree outside that directory (e.g., `../cloglog-prod` is the prod worktree — never touch it).
```

- [ ] **Step 2: Verify the change looks correct**

```bash
grep -A 3 "Step 1: Detect" plugins/cloglog/skills/close-wave/SKILL.md
```

Expected: the new filter text appears, not the old "anything beyond the main worktree" text.

- [ ] **Step 3: Commit**

```bash
git add plugins/cloglog/skills/close-wave/SKILL.md
git commit -m "fix(close-wave): filter worktrees to .claude/worktrees/ path, protect prod worktree"
```

---

## Task 5: Update MCP server default backend URL

**Files:**
- Modify: `mcp-server/src/index.ts`

- [ ] **Step 1: Change the default CLOGLOG_URL**

In `mcp-server/src/index.ts`, find line 12:

```typescript
const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8000'
```

Change to:

```typescript
const CLOGLOG_URL = process.env.CLOGLOG_URL ?? 'http://localhost:8001'
```

- [ ] **Step 2: Build and verify**

```bash
cd mcp-server && npm run build 2>&1 | tail -5
```

Expected: build succeeds, no errors.

- [ ] **Step 3: Run MCP server tests**

```bash
cd mcp-server && npm test 2>&1 | tail -10
```

Expected: all tests pass (the URL change only affects the default fallback, not test behaviour since tests mock the HTTP client).

- [ ] **Step 4: Commit**

```bash
git add mcp-server/src/index.ts mcp-server/dist/
git commit -m "fix(mcp): default CLOGLOG_URL to prod port 8001"
```

---

## Task 6: Create prod worktree and start prod server (one-time setup)

This task is manual setup — not committed to git. Run these steps once on the machine.

- [ ] **Step 1: Create the prod worktree**

From the repo root:

```bash
git worktree add ../cloglog-prod origin/main
```

Verify:

```bash
git worktree list
```

Expected output includes a line like:
```
/home/sachin/code/cloglog-prod  <commit-hash> [detached]
```

- [ ] **Step 2: Install dependencies in the prod worktree**

```bash
cd ../cloglog-prod && uv sync
```

Expected: dependencies sync without errors.

- [ ] **Step 3: Run migrations (sanity check)**

```bash
cd ../cloglog-prod && uv run alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade ...` or "No upgrade needed."

- [ ] **Step 4: Start the prod server**

Open a dedicated zellij pane (or run in background):

```bash
make prod
```

Expected: gunicorn starts, logs show two workers booting:
```
[INFO] Starting gunicorn 23.x.x
[INFO] Listening at: http://0.0.0.0:8001
[INFO] Booting worker with pid: XXXX
[INFO] Booting worker with pid: XXXX
```

- [ ] **Step 5: Smoke test prod**

```bash
curl -s http://localhost:8001/health | python3 -m json.tool
```

Expected: `{"status": "ok"}` or equivalent health response.

---

## Task 7: Switch Cloudflare tunnel to port 8001

This is a manual step — the cloudflared config is not committed to git.

- [ ] **Step 1: Update cloudflared config**

Edit `~/.cloudflared/config.yml`. Change the ingress service:

```yaml
# Before:
ingress:
  - hostname: cloglog.voxdez.com
    service: http://localhost:8000

# After:
ingress:
  - hostname: cloglog.voxdez.com
    service: http://localhost:8001
  - service: http_status:404
```

- [ ] **Step 2: Restart cloudflared**

```bash
kill -HUP $(pgrep cloudflared)
```

If that doesn't reload the config, restart the process fully:

```bash
kill $(pgrep cloudflared)
cloudflared tunnel run cloglog-webhooks &
```

- [ ] **Step 3: Verify webhook delivery reaches prod**

Send a test request through the tunnel:

```bash
curl -s https://cloglog.voxdez.com/health | python3 -m json.tool
```

Expected: same `{"status": "ok"}` response as the direct localhost:8001 check.

- [ ] **Step 4: Verify dev server is still reachable locally**

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected: health response — dev server unaffected.

---

## Task 8: Verify make promote is zero-downtime

- [ ] **Step 1: Make a trivial change to main (or use current HEAD)**

If you need something to promote, push a no-op commit:

```bash
git commit --allow-empty -m "chore: promote test"
BOT_TOKEN=$(uv run --with "PyJWT[crypto]" --with requests scripts/gh-app-token.py)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
git remote set-url origin "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git"
git push origin main
```

- [ ] **Step 2: Run make promote and watch for continuity**

In one terminal, start a background curl loop to watch for downtime:

```bash
while true; do curl -s -o /dev/null -w "%{http_code} %{time_total}\n" http://localhost:8001/health; sleep 0.2; done &
CURL_PID=$!
```

In another terminal (or same terminal after backgrounding):

```bash
make promote
```

- [ ] **Step 3: Verify no 5xx during promote**

```bash
kill $CURL_PID
```

Review the curl output. Expected: all responses are `200`, response times stay under 1 second. No gaps or 5xx codes during the HUP rotation.

- [ ] **Step 4: Verify prod is running new code**

```bash
curl -s http://localhost:8001/health | python3 -m json.tool
git -C ../cloglog-prod log --oneline -1
```

Expected: the commit shown matches the latest `origin/main`.
