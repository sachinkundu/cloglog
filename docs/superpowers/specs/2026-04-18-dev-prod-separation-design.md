# Dev/Prod Separation Design

**Date:** 2026-04-18
**Status:** Approved

## Problem

The cloglog backend runs as a single process (`make dev`) that serves both local development and live GitHub webhook traffic through a Cloudflare tunnel. Uvicorn's `--reload` flag restarts the worker process whenever source files change. During that restart window (typically < 1 second), the server is unavailable — and GitHub webhook deliveries are dropped permanently. This is how the codex reviewer missed PR #138.

The root cause is that dev changes and production traffic share the same process and the same filesystem path.

## Goals

- `make prod` runs a stable production server immune to dev file changes
- `make promote` deploys merged `main` with zero dropped webhook deliveries
- Dev retains hot-reload for fast iteration
- No system-wide services (no systemd, no root)
- Path toward Railway deployment (F-35) is not obstructed

## Architecture

Two independent processes, completely isolated at the filesystem level:

| | Dev | Prod |
|---|---|---|
| Command | `uvicorn --reload` | `gunicorn UvicornWorker` |
| Port | 8000 | 8001 |
| Directory | `/home/sachin/code/cloglog` (main worktree) | `../cloglog-prod` (prod worktree) |
| Reload | hot (file watcher triggers restart) | graceful (SIGHUP rotates workers) |
| Cloudflare tunnel | not exposed | `cloglog.voxdez.com → localhost:8001` |
| Database | shared Postgres | shared Postgres |
| Source of truth | no | yes — agents and MCP connect here |

### Why filesystem isolation matters

Both processes read Python source from disk. Without separate directories, a dev file save would be picked up by gunicorn workers on the next SIGHUP (`make promote`), leaking uncommitted code into prod. The prod worktree only ever contains code that has been pushed to and pulled from `origin/main`.

### Prod worktree

```bash
git worktree add ../cloglog-prod origin/main
```

Path: `../cloglog-prod` (sibling directory, outside the repo root). This path is:
- Outside `.claude/worktrees/` → ignored by the reconcile skill's path filter
- Outside the main working tree → ignored by uvicorn's `--reload` file watcher
- Tracked in `.cloglog/config.yaml` as `prod_worktree_path` for explicit protection

The prod worktree tracks `origin/main` and is only updated by `make promote`. It does not participate in the agent worktree lifecycle and must never be removed by `close-wave` or `reconcile`.

## Makefile Targets

### `make prod`
Starts the production server in the foreground (run in a dedicated zellij pane):

```makefile
prod:
	@echo "Starting cloglog prod server (port 8001)..."
	@cd ../cloglog-prod && \
	  uv run gunicorn src.gateway.app:create_app \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers 2 \
	    --bind 0.0.0.0:8001 \
	    --pid /tmp/cloglog-prod.pid \
	    --error-logfile /tmp/cloglog-prod.log \
	    --log-level info \
	    --access-logfile /tmp/cloglog-prod-access.log \
	    --factory
```

Two workers: one handles live requests while the other restarts on SIGHUP, then they swap.

### `make promote`
Deploys the latest `origin/main` to prod with zero-downtime worker rotation:

```makefile
promote:
	@echo "Promoting origin/main to prod..."
	@git -C ../cloglog-prod pull origin main
	@cd ../cloglog-prod && uv sync
	@cd ../cloglog-prod && uv run alembic upgrade head
	@kill -HUP $$(cat /tmp/cloglog-prod.pid)
	@echo "Promoted. New workers loading..."
```

Migrations run before the HUP so new workers start against an already-migrated schema. Old workers finish in-flight requests before exiting.

### `make prod-logs`
```makefile
prod-logs:
	@tail -f /tmp/cloglog-prod.log /tmp/cloglog-prod-access.log
```

### `make prod-stop`
```makefile
prod-stop:
	@kill $$(cat /tmp/cloglog-prod.pid) && echo "Prod server stopped."
```

### `make dev` — hot-reload scope hardening
Extend `--reload-exclude` to cover more noise sources:

```makefile
dev:
	uv run uvicorn src.gateway.app:create_app --factory \
	  --host 0.0.0.0 --port 8000 --reload \
	  --reload-exclude '.claude/worktrees' \
	  --reload-exclude '__pycache__' \
	  --reload-exclude '*.pyc'
```

## Configuration Changes

### `.cloglog/config.yaml`
Add `prod_worktree_path` and update `backend_url`:

```yaml
prod_worktree_path: ../cloglog-prod
backend_url: http://localhost:8001   # prod is source of truth
```

`backend_url` is used by MCP tools and agents to reach the board API. It now points to prod.

### Cloudflare tunnel
One-time manual change in `~/.cloudflared/config.yml`:

```yaml
ingress:
  - hostname: cloglog.voxdez.com
    service: http://localhost:8001   # was 8000
  - service: http_status:404
```

Restart cloudflared after the change: `kill -HUP $(pgrep cloudflared)` or restart the tunnel process.

## Worktree Protection

The prod worktree at `../cloglog-prod` must not be touched by agent cleanup automation.

### Reconcile skill
Already safe: filters to `.claude/worktrees/wt-*` paths only. `../cloglog-prod` is outside this scope.

### Close-wave skill
**Requires update:** Step 1 currently detects "anything beyond the main worktree." Change the filter to match reconcile: only manage worktrees whose path starts with `$(git rev-parse --show-toplevel)/.claude/worktrees/`. This makes both skills consistent and protects any future long-lived worktrees.

### Second line of defence
Every skill that iterates worktrees reads `prod_worktree_path` from `.cloglog/config.yaml` and skips that path explicitly, regardless of where it lives.

## MCP Server

The MCP server's `BACKEND_URL` env var must point to prod (`http://localhost:8001`). Agents interact with the live board via prod; dev is for local testing only.

If the MCP server reads `backend_url` from `.cloglog/config.yaml`, the config change above is sufficient. Otherwise update the MCP server's `.env` or config.

## Prod Setup (One-Time)

```bash
# 1. Create prod worktree
git worktree add ../cloglog-prod origin/main

# 2. Install dependencies in prod worktree
cd ../cloglog-prod && uv sync

# 3. Run migrations
cd ../cloglog-prod && uv run alembic upgrade head

# 4. Update cloudflared config (see above), restart cloudflare tunnel

# 5. Start prod server
make prod
```

## Review Engine Source Root

The F-36 code-review engine invokes `codex -C <path>` with a filesystem root that codex is free to read. Until T-255, that path was `Path.cwd()` — which, for the prod server, is `../cloglog-prod`. That prod checkout only advances when `make promote` runs, so any PR review that referenced code merged to `main` but not yet promoted produced a false-negative (codex could not see the file on disk).

The fix is a new `REVIEW_SOURCE_ROOT` environment variable (`Settings.review_source_root`) that overrides the cwd fallback. Prod deploy **must** set it:

```bash
REVIEW_SOURCE_ROOT=/home/sachin/code/cloglog
```

i.e. the directory hosting the `main` checkout that dev continuously pulls, not the prod worktree. Without it, the reviewer falls back to `Path.cwd()` and the T-255 bug returns silently. The backend logs the resolved path and its HEAD SHA once at boot (`Review source root: <path> @ <sha> (<source>)`) so a stale checkout is visible in the logs.

When F-35 (Railway deployment) lands, this variable is set in the deploy environment; the local prod-worktree concept goes away.

## Relationship to F-35 (Railway Deployment)

When Railway deployment lands, `make prod` and `make promote` are replaced by Railway's deploy pipeline. The `prod_worktree_path` concept goes away. The Cloudflare tunnel is replaced by Railway's public URL. This design is explicitly temporary infrastructure — it solves the immediate problem without coupling anything to the local machine permanently.
