.PHONY: help install test test-board test-agent test-document test-gateway test-e2e test-e2e-browser test-e2e-browser-ui test-e2e-browser-headed test-e2e-browser-report invariants lint typecheck coverage contract-check demo demo-check quality run-backend prod prod-bg promote prod-logs prod-stop db-up db-down db-migrate db-revision db-refresh-from-prod sync-mcp-dist

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies
	uv sync --all-extras

# ── Testing ───────────────────────────────────

test: ## Run all backend tests
	uv run pytest tests/ -v --tb=short

test-board: ## Run Board context tests
	uv run pytest tests/board/ -v --tb=short

test-agent: ## Run Agent context tests
	uv run pytest tests/agent/ -v --tb=short

test-document: ## Run Document context tests
	uv run pytest tests/document/ -v --tb=short

test-gateway: ## Run Gateway context tests
	uv run pytest tests/gateway/ -v --tb=short

test-e2e: ## Run end-to-end tests
	uv run pytest tests/e2e/ -v --tb=short

test-e2e-browser: ## Run Playwright E2E browser tests
	cd tests/e2e/playwright && npx playwright test

test-e2e-browser-ui: ## Run Playwright E2E tests with interactive UI
	cd tests/e2e/playwright && npx playwright test --ui

test-e2e-browser-headed: ## Run Playwright E2E tests in headed browser
	cd tests/e2e/playwright && npx playwright test --headed

test-e2e-browser-report: ## Run Playwright E2E tests and open HTML report
	cd tests/e2e/playwright && npx playwright test --reporter=html && npx playwright show-report

invariants: ## Run silent-failure pin tests (see docs/invariants.md)
	uv run pytest --tb=short -q \
	  tests/test_on_worktree_create_backend_url.py::test_hook_does_not_invoke_python_yaml \
	  tests/test_mcp_json_no_secret.py \
	  tests/test_no_destructive_migrations.py \
	  tests/test_check_demo_allowlist.py \
	  tests/test_check_demo_exemption_hash.py \
	  tests/agent/test_integration.py::TestForceUnregisterAPI::test_force_unregister_rejects_agent_token \
	  tests/agent/test_unit.py::TestAgentService::test_register_reconnect_preserves_branch_when_caller_sends_empty \
	  tests/e2e/test_access_control.py::test_worktrees_with_invalid_mcp_bearer_is_rejected \
	  tests/gateway/test_review_engine.py::TestResolvePrReviewRoot \
	  tests/gateway/test_review_engine.py::TestLatestCodexReviewIsApproval

# ── Quality ───────────────────────────────────

lint: ## Run linter
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

typecheck: ## Run type checker
	uv run mypy src/

coverage: ## Run tests with coverage report
	uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80

contract-check: ## Validate backend matches API contract
	@if ls docs/contracts/*.openapi.yaml 1>/dev/null 2>&1; then \
		uv run python scripts/check-contract.py; \
	else \
		echo "  No contract files, skipping"; \
	fi


demo: ## Run proof-of-work demo for current feature
	@echo "Running proof-of-work demo..."
	@scripts/run-demo.sh

demo-check: ## Check demo document exists and verifies
	@scripts/check-demo.sh

sync-mcp-dist: ## Rebuild mcp-server/dist and broadcast mcp_tools_updated to online worktrees (T-244)
	@uv run python scripts/sync_mcp_dist.py

quality: ## Run full quality gate (invariants fail-fast → lint → typecheck → test → coverage → contract → demo)
	@echo "── Invariants ──────────────────────────"
	@echo ""
	@echo "  Silent-failure pin tests (see docs/invariants.md):"
	@$(MAKE) --no-print-directory invariants && echo "    all passing        ✓" || (echo "    FAILED ✗ — a silent-failure invariant regressed. See docs/invariants.md for the rule behind each pin test." && exit 1)
	@echo ""
	@echo "── Backend ─────────────────────────────"
	@echo ""
	@echo "  Lint:"
	@uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && echo "    0 errors           ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
	@echo "  Types:"
	@uv run mypy src/ --no-error-summary 2>&1 | tail -1 | grep -q "Success" && echo "    0 errors           ✓" || (uv run mypy src/ && echo "    0 errors           ✓" || (echo "    FAILED ✗" && exit 1))
	@echo ""
	@echo "  Tests + Coverage:"
	@uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -q 2>&1 | tail -5
	@echo ""
	@echo "  Contract:"
	@$(MAKE) --no-print-directory contract-check && echo "    compliant          ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
	@echo "  Demo:"
	@$(MAKE) --no-print-directory demo-check && echo "    verified           ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
	@echo "── MCP server ──────────────────────────"
	@echo ""
	@echo "  Build + Tests:"
	@if [ -d mcp-server ]; then \
		$(MAKE) --no-print-directory -C mcp-server quality > /tmp/mcp-quality.out 2>&1 \
			&& tail -3 /tmp/mcp-quality.out | sed 's/^/    /' \
			|| (echo "    FAILED ✗" && cat /tmp/mcp-quality.out && exit 1); \
	else \
		echo "    (skipped — no mcp-server/)"; \
	fi
	@echo ""
	@echo "── Quality gate: PASSED ────────────────"

# ── Run ───────────────────────────────────────

dev: ## Start everything (db + migrate + backend + frontend)
	@scripts/preflight.sh
	@echo "Starting cloglog dev environment..."
	@docker compose up -d 2>/dev/null || true
	@echo "  Postgres: up"
	@uv run alembic upgrade head 2>&1 | tail -1
	@echo "  Migrations: applied"
	@# Kill old processes on ports 8000 and 5173 if still running
	@fuser -k 8000/tcp 2>/dev/null && echo "  Killed old backend on :8000" || true
	@fuser -k 5173/tcp 2>/dev/null && echo "  Killed old frontend on :5173" || true
	@HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		echo "  Frontend: http://localhost:5173"; \
		[ -n "$$HOST_IP" ] && echo "  Frontend: http://$$HOST_IP:5173 (tailnet)" || true; \
		echo "  Starting backend + frontend..."; \
		trap 'kill 0; fuser -k 8000/tcp 2>/dev/null; fuser -k 5173/tcp 2>/dev/null' EXIT INT TERM; \
		uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
			--reload-exclude '.claude/worktrees' \
			--reload-exclude '__pycache__' \
			--reload-exclude '*.pyc' & \
		if [ -n "$$HOST_IP" ]; then \
			VITE_API_URL_DEV=$${VITE_API_URL:-http://$$HOST_IP:8000/api/v1}; \
			echo "  API URL:  $$VITE_API_URL_DEV"; \
			(cd frontend && VITE_API_URL="$$VITE_API_URL_DEV" npm run dev -- --host 0.0.0.0) & \
		else \
			(cd frontend && npm run dev) & \
		fi; \
		wait

run-backend: ## Start the FastAPI backend
	uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
		--reload-exclude '.claude/worktrees' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc'

prod: ## Start prod server (gunicorn + vite preview, foreground — run in a zellij pane)
	@if [ -f /tmp/cloglog-prod.pid ] && kill -0 "$$(cat /tmp/cloglog-prod.pid)" 2>/dev/null; then \
		echo "ERROR: prod gunicorn is already running (pid $$(cat /tmp/cloglog-prod.pid)) on :8001."; \
		echo "       Use 'make promote' to rotate workers, or 'make prod-stop' first."; \
		exit 1; \
	fi
	@if ss -tln 2>/dev/null | awk '{print $$4}' | grep -qE '(^|:)8001$$'; then \
		echo "ERROR: port 8001 is in use by another process, but /tmp/cloglog-prod.pid does not claim it."; \
		echo "       Run 'ss -tlnp | grep :8001' to identify the owner, then 'make prod-stop' or clear it manually."; \
		exit 1; \
	fi
	@scripts/preflight.sh
	@HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		HOST=$${HOST_IP:-localhost}; \
		API_URL=$${VITE_API_URL:-http://$$HOST:8001/api/v1}; \
		echo "Starting cloglog prod server..."; \
		echo "  Backend:  http://localhost:8001"; \
		[ -n "$$HOST_IP" ] && echo "  Backend:  http://$$HOST_IP:8001 (tailnet)" || true; \
		echo "  Frontend: http://localhost:4173"; \
		[ -n "$$HOST_IP" ] && echo "  Frontend: http://$$HOST_IP:4173 (tailnet)" || true; \
		echo "  API URL:  $$API_URL"; \
		echo "  Tunnel:   https://cloglog.voxdez.com (systemd-managed; see docs/contracts/webhook-pipeline-spec.md)"; \
		echo "  Building frontend..."; \
		(cd ../cloglog-prod/frontend && npm ci --silent && VITE_API_URL="$$API_URL" npx vite build 2>&1 | tail -2); \
		echo "  Frontend: built"; \
		fuser -k 4173/tcp 2>/dev/null || true; \
		PREVIEW_HOST_FLAG=""; \
		[ -n "$$HOST_IP" ] && PREVIEW_HOST_FLAG="--host 0.0.0.0"; \
		trap 'kill 0; fuser -k 4173/tcp 2>/dev/null; rm -f /tmp/cloglog-prod-frontend.pid' EXIT INT TERM; \
		(cd ../cloglog-prod && uv run gunicorn src.gateway.asgi:app \
		    --worker-class uvicorn.workers.UvicornWorker \
		    --workers 2 \
		    --bind 0.0.0.0:8001 \
		    --pid /tmp/cloglog-prod.pid \
		    --error-logfile /tmp/cloglog-prod.log \
		    --access-logfile /tmp/cloglog-prod-access.log \
		    --log-level info 2>&1 | sed -u 's/^/[backend] /') & \
		(tail -F -n 0 /tmp/cloglog-prod.log 2>/dev/null | sed -u 's/^/[backend] /') & \
		(cd ../cloglog-prod/frontend && npm run preview -- --port 4173 $$PREVIEW_HOST_FLAG 2>&1 | sed -u 's/^/[frontend] /' & echo $$! > /tmp/cloglog-prod-frontend.pid) & \
		wait

prod-bg: ## Start prod server in background
	@if [ -f /tmp/cloglog-prod.pid ] && kill -0 "$$(cat /tmp/cloglog-prod.pid)" 2>/dev/null; then \
		echo "ERROR: prod gunicorn is already running (pid $$(cat /tmp/cloglog-prod.pid)) on :8001."; \
		echo "       Use 'make promote' to rotate workers, or 'make prod-stop' first."; \
		exit 1; \
	fi
	@if ss -tln 2>/dev/null | awk '{print $$4}' | grep -qE '(^|:)8001$$'; then \
		echo "ERROR: port 8001 is in use by another process, but /tmp/cloglog-prod.pid does not claim it."; \
		echo "       Run 'ss -tlnp | grep :8001' to identify the owner, then 'make prod-stop' or clear it manually."; \
		exit 1; \
	fi
	@scripts/preflight.sh
	@HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		HOST=$${HOST_IP:-localhost}; \
		API_URL=$${VITE_API_URL:-http://$$HOST:8001/api/v1}; \
		echo "Starting cloglog prod server (background)..."; \
		echo "  Backend:  http://localhost:8001"; \
		[ -n "$$HOST_IP" ] && echo "  Backend:  http://$$HOST_IP:8001 (tailnet)" || true; \
		echo "  Frontend: http://localhost:4173"; \
		[ -n "$$HOST_IP" ] && echo "  Frontend: http://$$HOST_IP:4173 (tailnet)" || true; \
		echo "  API URL:  $$API_URL"; \
		echo "  Tunnel:   https://cloglog.voxdez.com (systemd-managed; see docs/contracts/webhook-pipeline-spec.md)"; \
		(cd ../cloglog-prod/frontend && npm ci --silent && VITE_API_URL="$$API_URL" npx vite build 2>&1 | tail -2); \
		(cd ../cloglog-prod && uv run gunicorn src.gateway.asgi:app \
		    --worker-class uvicorn.workers.UvicornWorker \
		    --workers 2 \
		    --bind 0.0.0.0:8001 \
		    --pid /tmp/cloglog-prod.pid \
		    --error-logfile /tmp/cloglog-prod.log \
		    --access-logfile /tmp/cloglog-prod-access.log \
		    --log-level info \
		    --daemon); \
		fuser -k 4173/tcp 2>/dev/null || true; \
		PREVIEW_HOST_FLAG=""; \
		[ -n "$$HOST_IP" ] && PREVIEW_HOST_FLAG="--host 0.0.0.0"; \
		(cd ../cloglog-prod/frontend && npm run preview -- --port 4173 $$PREVIEW_HOST_FLAG & echo $$! > /tmp/cloglog-prod-frontend.pid); \
		echo "  Backend PID: $$(cat /tmp/cloglog-prod.pid)  Frontend PID: $$(cat /tmp/cloglog-prod-frontend.pid)"

promote: ## Deploy latest origin/main to prod with zero-downtime worker rotation
	@echo "Promoting origin/main to prod..."
	@git -C ../cloglog-prod pull origin main
	@cd ../cloglog-prod && uv sync
	@cd ../cloglog-prod/frontend && npm ci --silent
	@HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		HOST=$${HOST_IP:-localhost}; \
		API_URL=$${VITE_API_URL:-http://$$HOST:8001/api/v1}; \
		echo "  API URL:  $$API_URL"; \
		(cd ../cloglog-prod/frontend && VITE_API_URL="$$API_URL" npx vite build 2>&1 | tail -2); \
		(cd ../cloglog-prod && uv run alembic upgrade head); \
		if [ -f /tmp/cloglog-prod.pid ]; then kill -HUP $$(cat /tmp/cloglog-prod.pid) && echo "  Backend: rotated workers."; else echo "  Warning: gunicorn not running — start with make prod"; fi; \
		fuser -k 4173/tcp 2>/dev/null || true; \
		rm -f /tmp/cloglog-prod-frontend.pid; \
		PREVIEW_HOST_FLAG=""; \
		[ -n "$$HOST_IP" ] && PREVIEW_HOST_FLAG="--host 0.0.0.0"; \
		(cd ../cloglog-prod/frontend && npm run preview -- --port 4173 $$PREVIEW_HOST_FLAG & echo $$! > /tmp/cloglog-prod-frontend.pid); \
		echo "  Done — frontend rebuilt and restarted on :4173."; \
		[ -n "$$HOST_IP" ] && echo "  Tailnet: http://$$HOST_IP:4173" || true

prod-logs: ## Tail prod server logs
	@tail -f /tmp/cloglog-prod.log /tmp/cloglog-prod-access.log

prod-stop: ## Stop the prod server (backend + frontend only — tunnel is systemd-managed)
	@kill $$(cat /tmp/cloglog-prod.pid) 2>/dev/null && rm -f /tmp/cloglog-prod.pid && echo "  Backend: stopped." || true
	@kill $$(cat /tmp/cloglog-prod-frontend.pid) 2>/dev/null && rm -f /tmp/cloglog-prod-frontend.pid && echo "  Frontend: stopped." || true
	@fuser -k 4173/tcp 2>/dev/null && echo "  Frontend: killed by port." || true

# ── Database ──────────────────────────────────

db-up: ## Start PostgreSQL
	docker compose up -d

db-down: ## Stop PostgreSQL
	docker compose down

db-migrate: ## Run Alembic migrations
	uv run alembic upgrade head

db-revision: ## Create a new Alembic migration (usage: make db-revision msg="description")
	uv run alembic revision --autogenerate -m "$(msg)"

db-refresh-from-prod: ## Snapshot prod DB (cloglog) into dev DB (cloglog_dev)
	@echo "Refreshing cloglog_dev from cloglog..."
	@PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d postgres -c "DROP DATABASE IF EXISTS cloglog_dev;" >/dev/null
	@PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d postgres -c "CREATE DATABASE cloglog_dev OWNER cloglog;" >/dev/null
	@PGPASSWORD=cloglog_dev pg_dump -h 127.0.0.1 -U cloglog -d cloglog --no-owner --no-privileges 2>/dev/null | PGPASSWORD=cloglog_dev psql -h 127.0.0.1 -U cloglog -d cloglog_dev -q >/dev/null
	@echo "  cloglog_dev: seeded from cloglog ✓"
