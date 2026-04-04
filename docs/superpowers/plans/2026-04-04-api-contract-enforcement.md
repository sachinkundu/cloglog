# API Contract Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce API contracts between backend and frontend via OpenAPI specs designed before each wave, with automated validation in the quality gate.

**Architecture:** A DDD Architect agent designs an OpenAPI spec from the implementation plan. `create-worktree.sh` generates TypeScript types from it. `check-contract.py` validates the backend matches the contract. Both checks run in `make quality`.

**Tech Stack:** OpenAPI 3.1 YAML, `openapi-typescript` (npm), PyYAML (Python), FastAPI OpenAPI extraction.

---

### Task 1: Add PyYAML dependency

**Files:**
- Modify: `pyproject.toml:22-32`

- [ ] **Step 1: Add pyyaml to dev dependencies**

In `pyproject.toml`, add `pyyaml` to the `[project.optional-dependencies] dev` list:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "httpx>=0.28.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "sqlalchemy[mypy]>=2.0.36",
    "asyncpg>=0.30.0",
    "pyyaml>=6.0.0",
]
```

- [ ] **Step 2: Install**

Run: `uv sync --all-extras`
Expected: pyyaml installed successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pyyaml dev dependency for contract validation"
```

---

### Task 2: Add openapi-typescript dependency to frontend

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install openapi-typescript**

Run: `cd frontend && npm install --save-dev openapi-typescript`

- [ ] **Step 2: Verify installation**

Run: `cd frontend && npx openapi-typescript --help`
Expected: Usage information printed

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add openapi-typescript dev dependency for contract type generation"
```

---

### Task 3: Create `scripts/extract-openapi.py`

This script statically extracts the current backend OpenAPI schema to a JSON file. Used by the architect agent and contract checker.

**Files:**
- Create: `scripts/extract-openapi.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Extract the FastAPI app's OpenAPI schema to stdout as JSON.

Usage: uv run python scripts/extract-openapi.py > openapi.json
"""

import json
import sys

from src.gateway.app import create_app

app = create_app()
schema = app.openapi()
json.dump(schema, sys.stdout, indent=2, default=str)
print()  # trailing newline
```

- [ ] **Step 2: Verify it works**

Run: `uv run python scripts/extract-openapi.py | head -20`
Expected: JSON output starting with `{"openapi": "3.1.0", "info": {"title": "cloglog"...`

- [ ] **Step 3: Commit**

```bash
git add scripts/extract-openapi.py
git commit -m "feat: add script to extract OpenAPI schema from FastAPI app"
```

---

### Task 4: Create `scripts/check-contract.py`

The core enforcement script. Compares the runtime OpenAPI schema against designed contract files.

**Files:**
- Create: `scripts/check-contract.py`
- Test: `tests/test_check_contract.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the contract checker script."""

import json
import subprocess
import tempfile
from pathlib import Path

import yaml


def _run_checker(contracts_dir: str) -> subprocess.CompletedProcess[str]:
    """Run check-contract.py with a custom contracts directory."""
    return subprocess.run(
        ["uv", "run", "python", "scripts/check-contract.py", "--contracts-dir", contracts_dir],
        capture_output=True,
        text=True,
    )


def test_no_contract_files_skips():
    """When no contract files exist, checker exits 0."""
    with tempfile.TemporaryDirectory() as d:
        result = _run_checker(d)
        assert result.returncode == 0
        assert "No contract files found" in result.stdout


def test_matching_contract_passes():
    """When contract matches the runtime schema, checker exits 0."""
    # Extract current schema
    extract = subprocess.run(
        ["uv", "run", "python", "scripts/extract-openapi.py"],
        capture_output=True, text=True,
    )
    runtime_schema = json.loads(extract.stdout)

    # Build a contract that matches one endpoint exactly
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {
            "/api/v1/projects": {
                "get": runtime_schema["paths"]["/api/v1/projects"]["get"]
            }
        },
        "components": runtime_schema.get("components", {}),
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_missing_endpoint_fails():
    """When contract defines an endpoint the backend doesn't have, checker exits 1."""
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {
            "/api/v1/nonexistent": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    }
                }
            }
        },
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 1
        assert "/api/v1/nonexistent" in result.stdout


def test_missing_response_field_fails():
    """When contract expects a field the backend response doesn't have, checker exits 1."""
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {
            "/api/v1/projects": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["id", "name", "totally_fake_field"],
                                            "properties": {
                                                "id": {"type": "string"},
                                                "name": {"type": "string"},
                                                "totally_fake_field": {"type": "string"},
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 1
        assert "totally_fake_field" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_check_contract.py -v`
Expected: FAIL — `scripts/check-contract.py` doesn't exist yet

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""Validate that the FastAPI backend matches the designed API contracts.

Compares the runtime OpenAPI schema against all contract files in
docs/contracts/*.openapi.yaml. Exits non-zero if any differences found.

Usage:
    uv run python scripts/check-contract.py
    uv run python scripts/check-contract.py --contracts-dir path/to/contracts
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from src.gateway.app import create_app


def load_runtime_schema() -> dict:
    """Extract the current OpenAPI schema from FastAPI."""
    app = create_app()
    return app.openapi()


def load_contracts(contracts_dir: Path) -> dict:
    """Load and merge all contract YAML files."""
    merged_paths: dict = {}
    merged_components: dict = {}

    for f in sorted(contracts_dir.glob("*.openapi.yaml")):
        with open(f) as fh:
            contract = yaml.safe_load(fh)
        merged_paths.update(contract.get("paths", {}))
        for key, val in contract.get("components", {}).items():
            if key not in merged_components:
                merged_components[key] = {}
            merged_components[key].update(val)

    return {"paths": merged_paths, "components": merged_components}


def resolve_ref(ref: str, schema: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = schema
    for part in parts:
        node = node[part]
    return node


def get_response_properties(
    endpoint_schema: dict, full_schema: dict
) -> dict[str, set[str]]:
    """Extract response field names per status code from an endpoint schema."""
    result: dict[str, set[str]] = {}
    for status_code, resp in endpoint_schema.get("responses", {}).items():
        content = resp.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})
        result[status_code] = _extract_field_names(schema, full_schema)
    return result


def _extract_field_names(schema: dict, full_schema: dict) -> set[str]:
    """Recursively extract field names from a schema, resolving $ref."""
    if "$ref" in schema:
        schema = resolve_ref(schema["$ref"], full_schema)

    # Array — look at items
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return _extract_field_names(items, full_schema)

    # Object with properties
    props = schema.get("properties", {})
    return set(props.keys())


def check_endpoint(
    path: str,
    method: str,
    contract_op: dict,
    runtime_op: dict,
    contract_full: dict,
    runtime_full: dict,
) -> list[str]:
    """Compare a single endpoint between contract and runtime. Returns errors."""
    errors: list[str] = []

    contract_responses = get_response_properties(contract_op, contract_full)
    runtime_responses = get_response_properties(runtime_op, runtime_full)

    for status_code, contract_fields in contract_responses.items():
        if not contract_fields:
            continue  # Skip if contract doesn't specify fields

        runtime_fields = runtime_responses.get(status_code, set())
        if not runtime_fields:
            # Runtime might use a $ref we can resolve
            continue

        missing = contract_fields - runtime_fields
        if missing:
            errors.append(
                f"  {method.upper()} {path} [{status_code}]: "
                f"contract expects fields {sorted(missing)} but backend response is missing them. "
                f"Backend has: {sorted(runtime_fields)}"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check API contract compliance")
    parser.add_argument(
        "--contracts-dir",
        default="docs/contracts",
        help="Directory containing *.openapi.yaml contract files",
    )
    args = parser.parse_args()

    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.exists() or not list(contracts_dir.glob("*.openapi.yaml")):
        print("No contract files found, skipping contract check")
        return 0

    runtime = load_runtime_schema()
    contract = load_contracts(contracts_dir)

    errors: list[str] = []
    warnings: list[str] = []

    for path, methods in contract["paths"].items():
        runtime_path = runtime.get("paths", {}).get(path)

        if runtime_path is None:
            errors.append(f"  MISSING endpoint: {path} (defined in contract, not in backend)")
            continue

        for method, contract_op in methods.items():
            if method in ("parameters", "summary", "description"):
                continue  # Skip non-method keys

            runtime_op = runtime_path.get(method)
            if runtime_op is None:
                errors.append(f"  MISSING method: {method.upper()} {path}")
                continue

            # Build full schemas for $ref resolution
            contract_full = {
                "components": contract.get("components", {}),
                "paths": contract["paths"],
            }
            runtime_full = {
                "components": runtime.get("components", {}),
                "paths": runtime.get("paths", {}),
            }

            endpoint_errors = check_endpoint(
                path, method, contract_op, runtime_op, contract_full, runtime_full
            )
            errors.extend(endpoint_errors)

    if errors:
        print("CONTRACT CHECK FAILED\n")
        for e in errors:
            print(e)
        if warnings:
            print("\nWarnings:")
            for w in warnings:
                print(w)
        return 1

    print("Contract check passed — backend matches all contract specifications")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_check_contract.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/check-contract.py tests/test_check_contract.py
git commit -m "feat: add contract checker that validates backend against OpenAPI contracts"
```

---

### Task 5: Create `scripts/generate-contract-types.sh`

Wrapper script that generates TypeScript types from an OpenAPI contract file.

**Files:**
- Create: `scripts/generate-contract-types.sh`

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
set -euo pipefail

# Generate TypeScript types from an OpenAPI contract file.
# Usage: ./scripts/generate-contract-types.sh <contract.openapi.yaml> [output-dir]
#
# Default output: frontend/src/api/generated-types.ts

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONTRACT_FILE="${1:?Usage: $0 <contract.openapi.yaml> [output-dir]}"
OUTPUT_DIR="${2:-$REPO_ROOT/frontend/src/api}"
OUTPUT_FILE="$OUTPUT_DIR/generated-types.ts"

if [[ ! -f "$CONTRACT_FILE" ]]; then
  echo "Error: Contract file not found: $CONTRACT_FILE"
  exit 1
fi

echo "Generating TypeScript types from: $CONTRACT_FILE"
echo "Output: $OUTPUT_FILE"

cd "$REPO_ROOT/frontend"
npx openapi-typescript "$CONTRACT_FILE" -o "$OUTPUT_FILE"

echo "Generated: $OUTPUT_FILE"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x scripts/generate-contract-types.sh`

- [ ] **Step 3: Verify it works (using the current runtime schema as a test contract)**

Run:
```bash
mkdir -p docs/contracts
uv run python scripts/extract-openapi.py > /tmp/test-contract.json
# openapi-typescript accepts JSON too
./scripts/generate-contract-types.sh /tmp/test-contract.json
head -20 frontend/src/api/generated-types.ts
```
Expected: TypeScript interfaces generated from the schema

- [ ] **Step 4: Clean up test output and commit**

```bash
rm -f /tmp/test-contract.json frontend/src/api/generated-types.ts
git add scripts/generate-contract-types.sh
git commit -m "feat: add script to generate TypeScript types from OpenAPI contracts"
```

---

### Task 6: Add `contract-check` target to Makefile

**Files:**
- Modify: `Makefile:41-53`

- [ ] **Step 1: Add the contract-check target and update quality gate**

Add the `contract-check` target before `quality`, and add it to the `quality` recipe:

```makefile
contract-check: ## Validate backend matches API contract
	@if ls docs/contracts/*.openapi.yaml 1>/dev/null 2>&1; then \
		uv run python scripts/check-contract.py; \
	else \
		echo "  No contract files, skipping"; \
	fi
```

Update the `quality` target to include contract checking. Add this block after the "Tests + Coverage" block and before the "Quality gate: PASSED" line:

```makefile
	@echo "  Contract:"
	@$(MAKE) --no-print-directory contract-check && echo "    compliant          ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
```

Also add `contract-check` to the `.PHONY` line at the top.

- [ ] **Step 2: Verify quality still passes (no contract files exist yet)**

Run: `make quality`
Expected: PASSED, with "No contract files, skipping" in output

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add contract-check to quality gate"
```

---

### Task 7: Create `docs/contracts/` directory with a baseline contract

Bootstrap the contract system by generating a contract from the current backend state. This becomes the baseline that future waves extend.

**Files:**
- Create: `docs/contracts/baseline.openapi.yaml`

- [ ] **Step 1: Generate the baseline contract**

```bash
mkdir -p docs/contracts
uv run python -c "
import yaml
from src.gateway.app import create_app

app = create_app()
schema = app.openapi()

# Write as YAML for readability
with open('docs/contracts/baseline.openapi.yaml', 'w') as f:
    yaml.dump(schema, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
"
```

- [ ] **Step 2: Verify contract check passes against it**

Run: `make contract-check`
Expected: "Contract check passed"

- [ ] **Step 3: Commit**

```bash
git add docs/contracts/baseline.openapi.yaml
git commit -m "feat: add baseline OpenAPI contract from current backend"
```

---

### Task 8: Generate TypeScript types and migrate frontend imports

Replace hand-written `types.ts` with generated types from the baseline contract.

**Files:**
- Create: `frontend/src/api/generated-types.ts` (auto-generated)
- Modify: `frontend/src/api/types.ts` → rename to `frontend/src/api/local-types.ts`
- Modify: `frontend/src/api/client.ts:1`
- Modify: `frontend/src/components/Sidebar.tsx:1`
- Modify: `frontend/src/components/Sidebar.test.tsx:5`
- Modify: `frontend/src/hooks/useBoard.ts:3`
- Modify: all other files that import from `'../api/types'` or `'./api/types'`

- [ ] **Step 1: Generate types from baseline contract**

Run: `./scripts/generate-contract-types.sh docs/contracts/baseline.openapi.yaml`

- [ ] **Step 2: Examine the generated types**

Run: `cat frontend/src/api/generated-types.ts`

Note: `openapi-typescript` generates types using the OpenAPI schema names (e.g., `components["schemas"]["WorktreeResponse"]`). These are accessed differently than the current hand-written interfaces. The generated file exports a `paths` type and a `components` type.

- [ ] **Step 3: Create a thin re-export file**

Rather than changing every import in every component, create `frontend/src/api/types.ts` that re-exports the generated types as the familiar interface names. This keeps the migration minimal and gives us a single place to map generated types to app-friendly names.

Read the generated file to see the exact schema names, then write `frontend/src/api/types.ts`:

```typescript
// Re-export generated API types as app-friendly names.
// DO NOT hand-write API response types here — they come from the OpenAPI contract.
// Only add frontend-only types (not API responses) in this file.

import type { components } from './generated-types'

// API response types — derived from OpenAPI contract
export type Project = components['schemas']['ProjectResponse']
export type ProjectWithKey = components['schemas']['ProjectWithKey']
export type Epic = components['schemas']['EpicResponse']
export type Feature = components['schemas']['FeatureResponse']
export type TaskCard = components['schemas']['TaskResponse']
export type Worktree = components['schemas']['WorktreeResponse']
export type DocumentSummary = components['schemas']['DocumentResponse']

// Frontend-only types (not from API)
export interface BoardColumn {
  status: string
  tasks: TaskCard[]
}

export interface BoardResponse {
  project_id: string
  project_name: string
  columns: BoardColumn[]
  total_tasks: number
  done_count: number
}

export type SSEEvent = {
  type: 'task_status_changed' | 'worktree_online' | 'worktree_offline' | 'document_attached'
  data: Record<string, string>
}
```

Note: The exact schema names (`ProjectResponse`, `WorktreeResponse`, etc.) must match what's in the generated file. Read the generated file first and adjust the names in this re-export to match. If `BoardResponse` is also in the generated types, use it from there too.

- [ ] **Step 4: Update the Sidebar test mock data to match the generated Worktree type**

The mock data in `frontend/src/components/Sidebar.test.tsx` must match the generated `WorktreeResponse` schema. Update the mock to include all required fields:

```typescript
const mockWorktrees: Worktree[] = [
  {
    id: 'wt1',
    project_id: 'p1',
    name: 'wt-backend',
    worktree_path: '/tmp/wt-backend',
    branch_name: 'wt-backend',
    status: 'online',
    current_task_id: null,
    last_heartbeat: '2026-04-04T08:00:00Z',
    created_at: '2026-04-04T08:00:00Z',
  },
  {
    id: 'wt2',
    project_id: 'p1',
    name: 'wt-frontend',
    worktree_path: '/tmp/wt-frontend',
    branch_name: 'wt-frontend',
    status: 'offline',
    current_task_id: null,
    last_heartbeat: null,
    created_at: '2026-04-04T08:00:00Z',
  },
]
```

Also update the test assertion that checks worktree status rendering to use `'online'` instead of `'active'`.

- [ ] **Step 5: Verify frontend compiles and tests pass**

Run:
```bash
cd frontend && npx tsc --noEmit && npx vitest run
```
Expected: No type errors, all tests pass

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/generated-types.ts frontend/src/api/types.ts frontend/src/components/Sidebar.test.tsx
git commit -m "feat: migrate frontend to generated API types from OpenAPI contract"
```

---

### Task 9: Update `create-worktree.sh` with contract support

Add contract file discovery, type generation, and CLAUDE.md contract instructions to the worktree creation script.

**Files:**
- Modify: `scripts/create-worktree.sh`

- [ ] **Step 1: Add contract discovery and type generation after dependency installation**

After the "Dependencies installed." line (after line 132), add:

```bash
# ── Contract setup ─────────────────────────────────────────

CONTRACTS_DIR="${REPO_ROOT}/docs/contracts"
CONTRACT_FLAG="${4:-}"  # Optional: explicit contract file path

if [[ -n "$CONTRACT_FLAG" ]]; then
  CONTRACT_FILE="$CONTRACT_FLAG"
elif ls "$CONTRACTS_DIR"/*.openapi.yaml 1>/dev/null 2>&1; then
  # Use the most recently modified contract
  CONTRACT_FILE="$(ls -t "$CONTRACTS_DIR"/*.openapi.yaml | head -1)"
else
  CONTRACT_FILE=""
fi

if [[ -n "$CONTRACT_FILE" ]]; then
  echo ""
  echo "Setting up API contract..."
  
  # Copy contract into worktree for easy reference
  cp "$CONTRACT_FILE" "$WORKTREE_DIR/CONTRACT.yaml"
  echo "  Copied contract: $(basename "$CONTRACT_FILE") → CONTRACT.yaml"
  
  # Generate TypeScript types for frontend worktrees
  if [[ "$WORKTREE_NAME" == wt-frontend* ]]; then
    echo "  Generating TypeScript types from contract..."
    (cd "$WORKTREE_DIR" && "$REPO_ROOT/scripts/generate-contract-types.sh" "$WORKTREE_DIR/CONTRACT.yaml" "$WORKTREE_DIR/frontend/src/api")
    echo "  Generated: frontend/src/api/generated-types.ts"
  fi
  
  echo "Contract setup complete."
fi
```

- [ ] **Step 2: Add contract instructions to the generated CLAUDE.md**

Before the `## Git` section in the CLAUDE.md heredoc (before line 195), add contract-specific instructions based on worktree type:

```bash
# Add contract section to CLAUDE.md if a contract exists
if [[ -n "$CONTRACT_FILE" ]]; then
  if [[ "$WORKTREE_NAME" == wt-frontend* ]]; then
    cat >> "$CLAUDE_MD" << 'CONTRACT_EOF'

## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.
Generated TypeScript types are at `frontend/src/api/generated-types.ts`.

**Rules:**
- Import ALL API response types from `../api/generated-types.ts` via the re-exports in `../api/types.ts`
- NEVER hand-write API response interfaces — they come from the OpenAPI contract
- If you need a field that doesn't exist in the generated types, STOP — the contract must be updated first, not worked around
- TypeScript compilation will fail if you use wrong field names or types
CONTRACT_EOF
  else
    cat >> "$CLAUDE_MD" << 'CONTRACT_EOF'

## API Contract

This wave has a strict API contract at `CONTRACT.yaml`.

**Rules:**
- All new/modified endpoints MUST match the contract exactly: path, method, field names, field types, enum values
- Pydantic response schemas must produce JSON that matches the contract's response schemas
- Run `make contract-check` before committing to verify compliance
- If you need to change the API shape, STOP — the contract must be updated first
CONTRACT_EOF
  fi
fi
```

- [ ] **Step 3: Verify the script still works**

Run: `./scripts/create-worktree.sh wt-test-contract docs/superpowers/plans/2026-04-04-api-contract-enforcement.md "Test contract setup"`
Expected: Worktree created with CONTRACT.yaml copied in and contract instructions in CLAUDE.md

- [ ] **Step 4: Clean up test worktree**

Run:
```bash
git worktree remove .claude/worktrees/wt-test-contract --force
git branch -D wt-test-contract
```

- [ ] **Step 5: Commit**

```bash
git add scripts/create-worktree.sh
git commit -m "feat: add contract discovery, type generation, and instructions to create-worktree.sh"
```

---

### Task 10: Create DDD Architect agent definition

Create a custom agent that the planning phase can spawn to design OpenAPI contracts.

**Files:**
- Create: `.claude/agents/ddd-architect.md`

- [ ] **Step 1: Write the agent definition**

```markdown
---
name: ddd-architect
description: Designs OpenAPI contracts for cross-boundary API endpoints from implementation plans
model: opus
tools:
  - Read
  - Write
  - Bash
  - Glob
  - Grep
---

# DDD Architect Agent

You design OpenAPI 3.1 contracts for API endpoints that cross bounded context boundaries.

## Your Task

Given an implementation plan, produce an OpenAPI YAML spec defining every endpoint that a frontend or another bounded context will consume.

## Process

1. Read the implementation plan provided to you
2. Extract the current backend OpenAPI schema:
   ```bash
   uv run python scripts/extract-openapi.py
   ```
3. Identify all endpoints the plan requires (new routes, modified responses)
4. For each endpoint, define in OpenAPI 3.1 format:
   - Path and HTTP method
   - Request body schema with field names, types, required/optional
   - Response schema with field names, types, required/optional
   - Status enum values listed explicitly (never bare `string` for status-like fields)
   - HTTP status codes
   - Auth requirement (note in description: "Requires Bearer token" or "Public")
   - A request/response example
5. Write the contract to the path specified in your task

## Constraints

- Every response field must have an explicit type with format — no `object`, `any`, or `{}`
- Status-like fields MUST use `enum` with all valid values
- If a frontend component will display data, the exact field must exist in the response — no client-side derivation
- Examples are REQUIRED for every request and response
- Field naming: `snake_case`, UUIDs as `type: string, format: uuid`, datetimes as `type: string, format: date-time`
- New endpoints must note which bounded context owns them (in description)
- Do NOT modify existing endpoint schemas unless the plan explicitly calls for it
- Base your work on the existing OpenAPI schema — extend it, don't reinvent

## Output

Write the contract as valid OpenAPI 3.1 YAML to the file path specified in your task.
After writing, validate it:
```bash
uv run python -c "import yaml; yaml.safe_load(open('OUTPUT_PATH')); print('Valid YAML')"
```
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/ddd-architect.md
git commit -m "feat: add DDD Architect agent for designing API contracts"
```

---

### Task 11: Create DDD Reviewer agent definition

**Files:**
- Create: `.claude/agents/ddd-reviewer.md`

- [ ] **Step 1: Write the agent definition**

```markdown
---
name: ddd-reviewer
description: Reviews OpenAPI contracts for completeness, consistency, and frontend consumability
model: opus
tools:
  - Read
  - Bash
  - Glob
  - Grep
---

# DDD Reviewer Agent

You review OpenAPI contracts designed by the DDD Architect agent.

## Your Task

Given a contract file and the implementation plan it was designed from, validate the contract is complete, consistent, and consumable by the frontend.

## Checks

1. **Completeness** — Every feature in the plan that crosses a context boundary has corresponding endpoints. Every frontend view described in the plan has the data it needs from response schemas alone.

2. **Naming consistency** — Field names are consistent across related endpoints. If one endpoint uses `status: "online"`, related endpoints and events also use `"online"`, not synonyms like `"active"`. Check all enum values across endpoints for consistency.

3. **Frontend consumability** — Can the frontend render everything it needs from each response without joining data from multiple endpoints or transforming field values? If a sidebar shows a "name", does the response have a `name` field?

4. **Backward compatibility** — Compare against the current backend schema:
   ```bash
   uv run python scripts/extract-openapi.py
   ```
   Existing endpoints that aren't being changed must not have their schemas altered.

5. **DDD boundary respect** — Endpoints don't expose internal model columns that aren't part of the public contract.

6. **Enum exhaustiveness** — Every status field has all valid values listed. Cross-reference with the plan.

## Output Format

If approved:
```
APPROVED

All checks passed. The contract covers N endpoints with consistent naming and complete response schemas.
```

If revision needed:
```
REVISION REQUIRED

1. [CHECK_NAME] Description of issue
   Suggested fix: What to change

2. [CHECK_NAME] Description of issue
   Suggested fix: What to change
```

## Rules

- Be specific — name exact fields, endpoints, and enum values in your feedback
- Reference the plan section that creates the requirement
- Maximum 3 revision rounds — after that, list remaining issues for user escalation
- Do NOT modify the contract file yourself — only provide feedback
```

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/ddd-reviewer.md
git commit -m "feat: add DDD Reviewer agent for validating API contracts"
```

---

### Task 12: Update CLAUDE.md Agent Learnings with contract workflow

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add contract enforcement section to Agent Learnings**

In the `## Agent Learnings` section, after the `### Cross-Context Integration` subsection, add:

```markdown
### API Contract Enforcement
- **Every wave must have an API contract** designed before worktrees launch. The contract is an OpenAPI YAML file at `docs/contracts/<wave-name>.openapi.yaml`.
- The contract is designed by the DDD Architect agent and reviewed by the DDD Reviewer agent during the planning phase.
- **Frontend worktrees**: Import API types from `generated-types.ts` (auto-generated from the contract). NEVER hand-write API response types.
- **Backend worktrees**: Implement endpoints matching the contract exactly. Run `make contract-check` before committing.
- If you need to change the API shape, STOP and update the contract first — don't work around it.
- `make quality` validates contract compliance automatically. Your commit will be blocked if your implementation drifts from the contract.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add API contract enforcement to Agent Learnings"
```

---

### Task 13: Run full quality gate

- [ ] **Step 1: Run make quality**

Run: `make quality`
Expected: PASSED, including the new contract check step

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: All pass

- [ ] **Step 3: Verify contract check works end-to-end**

Run: `make contract-check`
Expected: "Contract check passed — backend matches all contract specifications"
