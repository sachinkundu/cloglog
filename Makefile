.PHONY: help install test test-board test-agent test-document test-gateway test-e2e test-e2e-browser test-e2e-browser-ui test-e2e-browser-headed test-e2e-browser-report lint typecheck coverage contract-check demo demo-check quality run-backend prod prod-bg promote prod-logs prod-stop

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

quality: ## Run full quality gate (lint + typecheck + test + coverage)
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
	@echo "  Starting backend + frontend..."
	@trap 'kill 0; fuser -k 8000/tcp 2>/dev/null; fuser -k 5173/tcp 2>/dev/null' EXIT INT TERM; \
		uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
			--reload-exclude '.claude/worktrees' \
			--reload-exclude '__pycache__' \
			--reload-exclude '*.pyc' & \
		(cd frontend && npm run dev) & \
		wait

run-backend: ## Start the FastAPI backend
	uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
		--reload-exclude '.claude/worktrees' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc'

prod: ## Start prod server (gunicorn, port 8001, foreground — run in a zellij pane)
	@echo "Starting cloglog prod server on :8001..."
	@cd ../cloglog-prod && \
	  uv run gunicorn src.gateway.asgi:app \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers 2 \
	    --bind 0.0.0.0:8001 \
	    --pid /tmp/cloglog-prod.pid \
	    --error-logfile /tmp/cloglog-prod.log \
	    --access-logfile /tmp/cloglog-prod-access.log \
	    --log-level info

prod-bg: ## Start prod server in background
	@echo "Starting cloglog prod server on :8001 (background)..."
	@cd ../cloglog-prod && \
	  uv run gunicorn src.gateway.asgi:app \
	    --worker-class uvicorn.workers.UvicornWorker \
	    --workers 2 \
	    --bind 0.0.0.0:8001 \
	    --pid /tmp/cloglog-prod.pid \
	    --error-logfile /tmp/cloglog-prod.log \
	    --access-logfile /tmp/cloglog-prod-access.log \
	    --log-level info \
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

# ── Database ──────────────────────────────────

db-up: ## Start PostgreSQL
	docker compose up -d

db-down: ## Stop PostgreSQL
	docker compose down

db-migrate: ## Run Alembic migrations
	uv run alembic upgrade head

db-revision: ## Create a new Alembic migration (usage: make db-revision msg="description")
	uv run alembic revision --autogenerate -m "$(msg)"
