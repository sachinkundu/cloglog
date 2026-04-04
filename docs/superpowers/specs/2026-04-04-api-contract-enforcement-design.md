# API Contract Enforcement for Parallel Worktree Waves

**Date:** 2026-04-04
**Status:** Draft
**Problem:** Backend and frontend agents in parallel worktrees independently invent API shapes, causing field name mismatches, status enum drift, and missing fields that only surface during manual testing after all PRs are merged.

## Motivation

In wave-based parallel development, each worktree agent works in isolation:
- `wt-agent` implements `WorktreeResponse` with `branch_name`, `status: "online"`, `created_at`
- `wt-frontend` consumes it expecting `name`, `status: "active"`, `last_heartbeat`

Both pass their own test suites because backend tests validate Pydantic schemas and frontend tests mock the API against hand-written TypeScript types. The mismatch is only discovered when a human opens the dashboard after merging.

This design eliminates that class of bug by making the API contract a shared, enforced artifact designed before any code is written.

## Overview

Three phases: **Design** (before wave), **Generation** (during worktree creation), **Enforcement** (during quality gate).

```
Implementation plan written
        |
        v
DDD Architect agent designs OpenAPI spec from plan + existing schemas
        |
        v
DDD Reviewer agent validates completeness, consistency, consumability
        |
        v
Iterate (max 3 rounds) until APPROVED
        |
        v
OpenAPI spec committed to docs/contracts/<wave-name>.openapi.yaml
        |
        v
create-worktree.sh generates TypeScript types from spec
        |
        v
Backend worktrees implement against spec
Frontend worktrees import generated types
        |
        v
make quality validates implementation matches contract
```

## Phase 1: Contract Design

### DDD Architect Agent

A subagent spawned during the planning phase, after the implementation plan is written but before worktrees are created.

**Inputs:**
- The implementation plan (identifies what endpoints are needed)
- The backend's current OpenAPI schema, extracted statically via `python -c "from src.gateway.app import create_app; import json; print(json.dumps(create_app().openapi()))"` (no running server required)
- Previously designed contracts in `docs/contracts/`

**Process:**
1. Read the implementation plan and identify all cross-boundary endpoints (any endpoint that a frontend component or another context will consume)
2. Extract the current OpenAPI schema statically (see Inputs) to understand existing endpoints and naming conventions
3. For each new or modified endpoint, define:
   - Path and HTTP method
   - Request body schema (if applicable) with field names, types, required/optional
   - Response schema with field names, types, required/optional
   - Status enum values listed explicitly (never bare `string`)
   - HTTP status codes and error response shapes
   - Auth requirement (Bearer token or public)
   - A request/response example
4. Write the spec to `docs/contracts/<wave-name>.openapi.yaml`

**Constraints (baked into the agent's prompt):**
- Every field in a response schema must have an explicit type with format — no `object` or `any`
- Status-like fields must use `enum` with all valid values listed
- If a frontend component needs to display data, the exact field must exist in the response — no client-side derivation from other fields (e.g., if the sidebar shows a worktree name, the response must have a `name` field)
- Request and response `example` blocks are required for each endpoint
- Field naming follows project convention: `snake_case`, UUIDs as `string` with `format: uuid`, datetimes as `string` with `format: date-time`
- New endpoints must specify which bounded context owns them

### DDD Reviewer Agent

A second subagent that reviews the architect's output.

**Checks:**
1. **Completeness** — Every feature in the plan that crosses a context boundary has corresponding endpoints. Every frontend view described in the plan has the data it needs from the response schemas alone.
2. **Naming consistency** — Field names are consistent across related endpoints. If `WorktreeResponse` uses `status: "online"`, then the SSE event `worktree_online` and any other reference to worktree status also uses `"online"`. No synonyms (`active`/`online`, `name`/`branch_name`).
3. **Frontend consumability** — Can the frontend render everything it needs from each response without joining data from multiple endpoints or transforming field values? If not, the response schema is incomplete.
4. **Backward compatibility** — Existing endpoints that aren't being changed must not have their schemas altered. New required fields on existing responses break existing consumers.
5. **DDD boundary respect** — Endpoints don't expose internal model columns that aren't part of the public contract. No leaking `_metadata` or internal IDs that consumers shouldn't depend on.
6. **Enum exhaustiveness** — Every status field has all valid values listed. The reviewer cross-references with the plan to ensure no status values are missing.

**Output format:**
```
APPROVED
```
or:
```
REVISION REQUIRED

1. [COMPLETENESS] WorktreeResponse missing `name` field — Sidebar.tsx needs to display a worktree name but the response only has `worktree_path` and `branch_name`.
   Suggested fix: Add `name: string` field.

2. [CONSISTENCY] WorktreeResponse uses status "online"/"offline" but SSEEvent type uses "worktree_active"/"worktree_inactive".
   Suggested fix: Align SSE event names to "worktree_online"/"worktree_offline".
```

**Iteration:** Maximum 3 rounds. If the reviewer still has issues after 3 rounds, the process stops and escalates to the user with the remaining issues listed.

## Phase 2: Code Generation

### Changes to `create-worktree.sh`

After creating the worktree and installing dependencies, the script:

1. **Finds the active contract** — looks for the most recent `docs/contracts/*.openapi.yaml` file, or accepts a `--contract` flag to specify one explicitly
2. **Generates TypeScript types** — runs `npx openapi-typescript docs/contracts/<wave>.openapi.yaml -o frontend/src/api/generated-types.ts` in the worktree
3. **Copies the contract spec** into the worktree root as `CONTRACT.yaml` for easy reference

### Changes to worktree CLAUDE.md

**For frontend worktrees** (`wt-frontend`, `wt-frontend-*`), the generated CLAUDE.md adds:

```markdown
## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.
Generated TypeScript types are at `frontend/src/api/generated-types.ts`.

**Rules:**
- Import ALL API response types from `../api/generated-types.ts`
- NEVER hand-write API response interfaces in `types.ts` or inline
- If you need a field that doesn't exist in the generated types, STOP — the contract must be updated first, not worked around
- TypeScript compilation will fail if you use wrong field names or types
```

**For backend worktrees** (`wt-board`, `wt-agent`, `wt-document`, `wt-gateway`), the generated CLAUDE.md adds:

```markdown
## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.

**Rules:**
- All new/modified endpoints MUST match the contract exactly: path, method, field names, field types, enum values
- Pydantic response schemas must produce JSON that matches the contract's response schemas
- Run `make contract-check` before committing to verify compliance
- If you need to change the API shape, STOP — the contract must be updated first
```

## Phase 3: Enforcement

### Backend: `scripts/check-contract.py`

A Python script that runs as part of `make quality`:

```
1. Load the FastAPI app and extract its runtime OpenAPI schema (same as /openapi.json)
2. Load all contract files from docs/contracts/*.openapi.yaml and merge them (each wave's contract is additive — it defines the endpoints that wave adds or modifies)
3. For each endpoint defined in the contract:
   a. Verify the path and method exist in the runtime schema
   b. Compare request body schema: field names, types, required fields
   c. Compare response schema: field names, types, required fields, enum values
   d. Compare status codes
4. Report all differences as errors
5. Exit non-zero if any differences found
```

**What it catches:**
- Missing endpoints (contract says `GET /projects/{id}/worktrees` exists, backend doesn't have it)
- Field name mismatches (`name` in contract, `branch_name` in implementation)
- Type mismatches (`string` in contract, `integer` in implementation)
- Missing fields (contract says `last_heartbeat` is in the response, implementation doesn't include it)
- Enum drift (contract says `["online", "offline"]`, implementation allows `"active"`)
- Extra undocumented fields in responses (warning, not error — allows gradual adoption)

### Frontend: TypeScript compilation

- `generated-types.ts` is the single source of truth for API types
- Components that import from it get compile-time checking for free
- If a component uses `wt.name` but the generated type doesn't have `name`, `tsc --noEmit` fails
- Already runs as part of `make quality` via the frontend build step

### Makefile integration

```makefile
contract-check:  ## Validate backend matches API contract
	@if ls docs/contracts/*.openapi.yaml 1>/dev/null 2>&1; then \
		echo "Checking API contract compliance..."; \
		uv run python scripts/check-contract.py; \
	else \
		echo "No contract files found, skipping contract check"; \
	fi

quality: lint typecheck test contract-check  ## Full quality gate
```

The `contract-check` target is a no-op when no contract files exist (for branches/waves that predate this system), so it's safe to add unconditionally.

## Migration: Existing `types.ts`

The current hand-written `frontend/src/api/types.ts` will be replaced by the generated file for types that have a contract. The migration path:

1. Generate the baseline contract from the current backend's OpenAPI schema (one-time bootstrap)
2. Generate `generated-types.ts` from it
3. Update `client.ts` and all components to import from `generated-types.ts`
4. Delete the hand-written interfaces that are now generated
5. Any types that are frontend-only (not API responses) stay in a separate `frontend/src/api/local-types.ts`

## Dependencies

**New npm dependency (dev):** `openapi-typescript` — generates TypeScript interfaces from OpenAPI 3.x specs. Zero runtime footprint, build-time only.

**No additional runtime Python dependencies** — `check-contract.py` uses `fastapi` and `json` which are already in the project.

**New Python dependency (dev):** `pyyaml` — for parsing OpenAPI YAML files in `check-contract.py`. Add to dev dependencies in `pyproject.toml`.

## File Locations

```
docs/contracts/
  <wave-name>.openapi.yaml       # Designed by architect agent, committed before wave
scripts/
  check-contract.py               # Backend contract validation
  generate-contract-types.sh      # Wrapper: openapi-typescript → generated-types.ts
frontend/src/api/
  generated-types.ts              # Auto-generated from contract (DO NOT EDIT)
  local-types.ts                  # Frontend-only types (not API responses)
  client.ts                       # Imports from generated-types.ts
```

## What This Prevents

| Bug class | How it's caught | When |
|-----------|----------------|------|
| Field name mismatch (`name` vs `branch_name`) | TypeScript compile error + contract-check diff | `make quality` |
| Status enum drift (`active` vs `online`) | contract-check enum comparison | `make quality` |
| Missing response fields | TypeScript error on frontend, schema diff on backend | `make quality` |
| Missing endpoints | contract-check path verification | `make quality` |
| Undocumented extra fields | contract-check warning | `make quality` |
| Frontend/backend designed independently | Architect+Reviewer agents agree on spec first | Before wave launch |

## Out of Scope

- **WebSocket/SSE event contracts** — SSE events are simpler (type + data dict) and less prone to drift. Can be added later if needed.
- **Inter-context API contracts** — Currently contexts communicate through the database, not HTTP. If context-to-context APIs are added, they should also get contracts.
- **Versioned APIs** — The project uses a single `/api/v1` prefix. Contract versioning can be added when multiple API versions are needed.
