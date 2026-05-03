.PHONY: help install test test-board test-agent test-document test-gateway test-e2e test-e2e-browser test-e2e-browser-ui test-e2e-browser-headed test-e2e-browser-report invariants lint typecheck coverage contract-check demo demo-check quality run-backend dev dev-env prod prod-bg promote verify-prod-protection prod-logs prod-stop db-up db-down db-migrate db-revision db-refresh-from-prod sync-mcp-dist

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
	  tests/test_database_url_required.py \
	  tests/test_on_worktree_create_backend_url.py::test_hook_does_not_invoke_python_yaml \
	  tests/test_mcp_json_no_secret.py \
	  tests/test_no_destructive_migrations.py \
	  tests/test_check_demo_allowlist.py \
	  tests/test_check_demo_exemption_hash.py \
	  tests/agent/test_integration.py::TestForceUnregisterAPI::test_force_unregister_rejects_agent_token \
	  tests/agent/test_unit.py::TestAgentService::test_register_reconnect_preserves_branch_when_caller_sends_empty \
	  tests/e2e/test_access_control.py::test_worktrees_with_invalid_mcp_bearer_is_rejected \
	  tests/gateway/test_review_engine.py::TestResolvePrReviewRoot \
	  tests/gateway/test_review_engine.py::TestLatestCodexReviewIsApproval \
	  tests/test_makefile_gunicorn_invocation.py \
	  tests/plugins/test_skills_no_remote_set_url.py \
	  tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py \
	  tests/gateway/test_notification_listener_toasts_on_unregister_filter.py \
	  tests/gateway/test_review_engine.py::TestPostReview::test_commit_id_included_when_head_sha_provided \
	  tests/gateway/test_review_engine.py::TestPostReview::test_commit_id_omitted_when_head_sha_empty \
	  tests/gateway/test_review_engine.py::TestFullFlowIntegration::test_degraded_path_includes_commit_id \
	  tests/gateway/test_review_engine_t248.py::TestOpencodeOnlyHost::test_session_cap_check_skipped_when_codex_unavailable \
	  tests/shared/test_event_bus_cross_worker.py::test_publisher_does_not_double_deliver_its_own_notify_echo \
	  tests/shared/test_event_bus_cross_worker.py::test_mirrored_events_do_not_reach_global_subscribers \
	  tests/shared/test_event_bus_cross_worker.py::test_oversize_payload_is_dropped_locally_logged_no_crash \
	  tests/plugins/test_init_on_fresh_repo.py::test_step3_block_writes_settings_with_no_placeholders \
	  tests/plugins/test_init_on_fresh_repo.py::test_step3_migration_preserves_non_cloglog_mcp_servers \
	  tests/plugins/test_agent_prompt_template_correct_inbox_paths.py \
	  tests/plugins/test_launch_skill_renders_clean_launch_sh.py \
	  tests/plugins/test_launch_skill_has_agent_started_timeout.py \
	  tests/plugins/test_close_tab_safety.py

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
	@# T-388: preflight runs FIRST so missing host deps (uv, docker, jq...)
	@# surface as their own actionable error before dev-env touches Postgres.
	@# Recursive $(MAKE) call (not a make prerequisite) keeps the ordering
	@# explicit; prerequisites would race ahead of the recipe.
	@scripts/preflight.sh
	@$(MAKE) --no-print-directory dev-env
	@echo "Starting cloglog dev environment..."
	@docker compose up -d 2>/dev/null || true
	@echo "  Postgres: up"
	@# T-388: clear any inherited DATABASE_URL so the generated `.env` wins.
	@# Pydantic-settings reads process env BEFORE .env, so a stale
	@# `export DATABASE_URL=.../cloglog` in the operator's shell would silently
	@# point `make dev` at the prod DB even with a correct .env on disk.
	@env -u DATABASE_URL uv run alembic upgrade head 2>&1 | tail -1
	@echo "  Migrations: applied"
	@# Kill old processes on ports 8000 and 5173 if still running
	@fuser -k 8000/tcp 2>/dev/null && echo "  Killed old backend on :8000" || true
	@fuser -k 5173/tcp 2>/dev/null && echo "  Killed old frontend on :5173" || true
	@HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		echo "  Frontend: http://localhost:5173"; \
		[ -n "$$HOST_IP" ] && echo "  Frontend: http://$$HOST_IP:5173 (tailnet)" || true; \
		echo "  Starting backend + frontend..."; \
		trap 'kill 0; fuser -k 8000/tcp 2>/dev/null; fuser -k 5173/tcp 2>/dev/null' EXIT INT TERM; \
		env -u DATABASE_URL uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
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
	@# T-388: clear inherited DATABASE_URL so the dev `.env` wins over a
	@# stale shell export from another checkout.
	env -u DATABASE_URL uv run uvicorn src.gateway.app:create_app --factory --host 0.0.0.0 --port 8000 --reload \
		--reload-exclude '.claude/worktrees' \
		--reload-exclude '__pycache__' \
		--reload-exclude '*.pyc'

# T-231: gunicorn invocations below pass --capture-output so worker stdout/stderr
# (FastAPI tracebacks, codex CLI errors, review_engine exceptions) reach the
# error-logfile. Without it, app stderr goes to the controlling terminal and is
# lost in --daemon mode — we hit this on PR #260, where review_engine swallowed
# an exception on a synchronize webhook and left no log to diagnose from.
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
		    --capture-output \
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
		    --capture-output \
		    --log-level info \
		    --daemon); \
		fuser -k 4173/tcp 2>/dev/null || true; \
		PREVIEW_HOST_FLAG=""; \
		[ -n "$$HOST_IP" ] && PREVIEW_HOST_FLAG="--host 0.0.0.0"; \
		(cd ../cloglog-prod/frontend && npm run preview -- --port 4173 $$PREVIEW_HOST_FLAG & echo $$! > /tmp/cloglog-prod-frontend.pid); \
		echo "  Backend PID: $$(cat /tmp/cloglog-prod.pid)  Frontend PID: $$(cat /tmp/cloglog-prod-frontend.pid)"

promote: ## Deploy latest origin/main to prod with zero-downtime worker rotation
	@echo "Promoting origin/main to prod..."
	@if [ ! -f /tmp/cloglog-prod.pid ]; then echo "ERROR: gunicorn not running — service is down, cannot promote. Run \`make prod\` to bring the backend up first, then \`make promote\`. (Spec §4.2: make prod is restart-only with no git operations; make promote requires a live backend so the worker rotation actually deploys the new SHA before the worktree, DB, or origin/prod are mutated.)"; exit 1; fi
	@PROD_PID=$$(cat /tmp/cloglog-prod.pid); \
		if ! kill -0 "$$PROD_PID" 2>/dev/null; then echo "ERROR: stale /tmp/cloglog-prod.pid (PID $$PROD_PID is dead) — service is down. Run \`make prod-stop && make prod\` to clean up and restart, then \`make promote\`."; exit 1; fi
	@git -C ../cloglog-prod fetch origin
	@git -C ../cloglog-prod merge --ff-only origin/main
	@cd ../cloglog-prod && uv sync
	@cd ../cloglog-prod/frontend && npm ci --silent
	@set -e; HOST_IP=$$(tailscale ip -4 2>/dev/null | head -n1 || true); \
		HOST=$${HOST_IP:-localhost}; \
		API_URL=$${VITE_API_URL:-http://$$HOST:8001/api/v1}; \
		echo "  API URL:  $$API_URL"; \
		(cd ../cloglog-prod/frontend && VITE_API_URL="$$API_URL" npx vite build 2>&1 | tail -2); \
		(cd ../cloglog-prod && uv run alembic upgrade head); \
		PROD_PID=$$(cat /tmp/cloglog-prod.pid); \
		kill -HUP "$$PROD_PID" && echo "  Backend: rotated workers (PID $$PROD_PID)."; \
		fuser -k 4173/tcp 2>/dev/null || true; \
		rm -f /tmp/cloglog-prod-frontend.pid; \
		PREVIEW_HOST_FLAG=""; \
		[ -n "$$HOST_IP" ] && PREVIEW_HOST_FLAG="--host 0.0.0.0"; \
		(cd ../cloglog-prod/frontend && npm run preview -- --port 4173 $$PREVIEW_HOST_FLAG & echo $$! > /tmp/cloglog-prod-frontend.pid); \
		echo "  Done — frontend rebuilt and restarted on :4173."; \
		[ -n "$$HOST_IP" ] && echo "  Tailnet: http://$$HOST_IP:4173" || true
	@git -C ../cloglog-prod push origin prod
	@echo "  origin/prod advanced — branch now reflects deployed code."

verify-prod-protection: ## Assert GitHub ruleset protection on `prod`. Uses the rulesets API (works on personal repos, unlike classic protection's `restrictions` field which is org-only). Requires operator's gh auth — the GitHub App PEM has no `administration` permission.
	@REPO=$$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || git remote get-url origin | sed 's|.*github.com[:/]||;s|\.git$$||'); \
		LIST=$$(gh api "repos/$$REPO/rulesets" 2>&1); \
		RC=$$?; \
		if [ $$RC -ne 0 ]; then \
			case "$$LIST" in \
				*"Resource not accessible by integration"*) \
					echo "FAIL: gh auth lacks repo access on $$REPO. App PEM has no admin scope by design — use operator's personal token."; \
					echo "Fix: \`gh auth login --scopes 'repo'\` as the operator before running this target."; \
					exit 2;; \
				*"Requires authentication"*|*"Bad credentials"*) \
					echo "FAIL: gh is not authenticated. Run \`gh auth login --scopes 'repo'\` as the operator and retry."; exit 2;; \
				*) \
					echo "FAIL: gh api error listing rulesets on $$REPO: $$LIST"; exit 1;; \
			esac; \
		fi; \
		IDS=$$(echo "$$LIST" | jq -r '[.[] | select(.enforcement == "active" and .target == "branch")] | .[].id'); \
		if [ -z "$$IDS" ]; then \
			echo "FAIL: no active branch ruleset on $$REPO. Apply rules in GitHub UI → Settings → Rules per docs/design/prod-branch-tracking.md §3.2 (rulesets API, NOT classic branch protection — classic restrictions don't work on personal repos)."; \
			exit 1; \
		fi; \
		ID=""; \
		for cand in $$IDS; do \
			CAND_RS=$$(gh api "repos/$$REPO/rulesets/$$cand" 2>/dev/null); \
			INC=$$(echo "$$CAND_RS" | jq -r '.conditions.ref_name.include // [] | join(",")'); \
			case ",$$INC," in *",refs/heads/prod,"*) ID=$$cand; RULESET=$$CAND_RS; break;; esac; \
		done; \
		if [ -z "$$ID" ]; then \
			echo "FAIL: no active branch ruleset on $$REPO targets refs/heads/prod (checked IDs: $$(echo $$IDS | tr '\n' ' ')). Spec §3.2 requires ruleset to cover refs/heads/prod."; \
			exit 1; \
		fi; \
		RULE_TYPES=$$(echo "$$RULESET" | jq -r '[.rules[].type] | join(",")'); \
		case ",$$RULE_TYPES," in *",required_linear_history,"*) :;; *) \
			echo "FAIL: ruleset $$ID on $$REPO is missing 'required_linear_history' rule (spec §3.2 clause 1: \"Require linear history\"). Have: [$$RULE_TYPES]."; \
			exit 1;; \
		esac; \
		case ",$$RULE_TYPES," in *",pull_request,"*) \
			echo "FAIL: ruleset $$ID on $$REPO has a 'pull_request' rule — but \`make promote\` pushes directly. Spec §3.2 clause 3 forbids the PR requirement on prod."; \
			exit 1;; \
		esac; \
		case ",$$RULE_TYPES," in *",update,"*) :;; *) \
			echo "FAIL: ruleset $$ID on $$REPO has no 'update' rule (spec §3.2 clause 2: \"Restrict pushes to the user's account\"). Without 'update', any actor with write access can push to prod, defeating the operator-only promotion gate. Add a 'Restrict updates' rule in GitHub UI → Rules → edit ruleset."; \
			exit 1;; \
		esac; \
		BYPASS_FIELD=$$(echo "$$RULESET" | jq 'has("bypass_actors")'); \
		BYPASS_NOTE="user-only push (update rule + admin bypass — operator-verified via UI)"; \
		if [ "$$BYPASS_FIELD" = "true" ]; then \
			BAD_BYPASS=$$(echo "$$RULESET" | jq -r '[.bypass_actors[]? | select(.actor_type != "RepositoryRole" or (.actor_type == "RepositoryRole" and .actor_id != 5))] | map("\(.actor_type):\(.actor_id // "?")") | join(",")'); \
			if [ -n "$$BAD_BYPASS" ]; then \
				echo "FAIL: ruleset $$ID on $$REPO grants bypass to non-admin actors [$$BAD_BYPASS]. Spec §3.2 forbids any app, agent, or team from bypassing prod protection — only the operator (RepositoryRole admin = id 5) is permitted."; \
				exit 1; \
			fi; \
			ADMIN_BYPASS_ALWAYS=$$(echo "$$RULESET" | jq -r '[.bypass_actors[]? | select(.actor_type == "RepositoryRole" and .actor_id == 5 and .bypass_mode == "always")] | length'); \
			if [ "$$ADMIN_BYPASS_ALWAYS" = "0" ]; then \
				echo "FAIL: ruleset $$ID on $$REPO has no admin bypass with bypass_mode=always — but \`make promote\` ends with a direct \`git push origin prod\`, which the 'update' rule blocks unless the operator can bypass. Add RepositoryRole admin (actor_id=5) with bypass_mode=always to bypass_actors via GitHub UI → Rules → edit ruleset → Bypass list."; \
				exit 1; \
			fi; \
			BYPASS_NOTE="user-only push (update rule + admin bypass — API-asserted)"; \
		else \
			echo "INFO: bypass_actors not surfaced in ruleset response — the field is gated to certain auth contexts (observed: missing from both GitHub App tokens and personal user tokens via gh api on personal repos, even when the UI shows entries correctly). Skipping programmatic bypass-list assertion. Operator MUST visually confirm in GitHub UI → Settings → Rules → bypass list shows exactly: RepositoryRole admin, bypass_mode=always, no apps/teams/integrations. Spec §3.2 still requires this configuration."; \
		fi; \
		WARN=""; \
		case ",$$RULE_TYPES," in *",non_fast_forward,"*) :;; *) WARN="$$WARN non_fast_forward(force-push not blocked)";; esac; \
		case ",$$RULE_TYPES," in *",deletion,"*) :;; *) WARN="$$WARN deletion(branch-delete not blocked)";; esac; \
		[ -n "$$WARN" ] && echo "WARN: ruleset is spec-compliant but missing recommended belt-and-braces rules:$$WARN"; \
		echo "OK: $$REPO ruleset $$ID covers refs/heads/prod. Spec §3.2 clauses: linear history (rule), no PR requirement (rule absent), $$BYPASS_NOTE. Rules: [$$RULE_TYPES]."

prod-logs: ## Tail prod server logs
	@tail -f /tmp/cloglog-prod.log /tmp/cloglog-prod-access.log

prod-stop: ## Stop the prod server (backend + frontend only — tunnel is systemd-managed)
	@kill $$(cat /tmp/cloglog-prod.pid) 2>/dev/null && rm -f /tmp/cloglog-prod.pid && echo "  Backend: stopped." || true
	@kill $$(cat /tmp/cloglog-prod-frontend.pid) 2>/dev/null && rm -f /tmp/cloglog-prod-frontend.pid && echo "  Frontend: stopped." || true
	@fuser -k 4173/tcp 2>/dev/null && echo "  Frontend: killed by port." || true

# ── Database ──────────────────────────────────

dev-env: ## Bootstrap dev .env (DATABASE_URL=cloglog_dev) — fail-loud if Postgres not reachable
	@# T-388: dev checkout must point at cloglog_dev, never the prod `cloglog`
	@# DB. Settings now refuses to start without an explicit DATABASE_URL, so
	@# the dev .env is no longer optional. The dev DB is created here
	@# explicitly — no silent CREATE-on-first-connect.
	@# Postgres readiness + DB creation go through `docker compose exec` so
	@# `make dev` does not require a host `psql` binary (preflight only checks
	@# uv/docker/node/npm/jq/cloudflared). The container always ships with
	@# psql; assuming a host install would silently mis-diagnose missing-psql
	@# as Postgres-unreachable.
	@docker compose up -d 2>/dev/null || true
	@for i in 1 2 3 4 5 6 7 8 9 10; do \
		docker compose exec -T postgres pg_isready -U cloglog -q 2>/dev/null && break; \
		[ $$i -eq 10 ] && { echo "ERROR: postgres unreachable after 10 attempts. Check 'docker compose logs postgres'." >&2; exit 1; }; \
		sleep 1; \
	done
	@if ! docker compose exec -T postgres psql -U cloglog -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='cloglog_dev'" | grep -q 1; then \
		docker compose exec -T postgres psql -U cloglog -d postgres -c "CREATE DATABASE cloglog_dev OWNER cloglog;" >/dev/null \
			|| { echo "ERROR: failed to create cloglog_dev database. Refusing to fall back to the prod 'cloglog' DB." >&2; exit 1; }; \
		echo "  cloglog_dev: created"; \
	fi
	@if [ ! -f .env ]; then \
		printf 'DATABASE_URL=postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_dev\n' > .env; \
		echo "  .env: written (DATABASE_URL → cloglog_dev)"; \
	elif ! grep -q '^DATABASE_URL=' .env; then \
		printf 'DATABASE_URL=postgresql+asyncpg://cloglog:cloglog_dev@127.0.0.1:5432/cloglog_dev\n' >> .env; \
		echo "  .env: appended DATABASE_URL → cloglog_dev"; \
	fi

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
