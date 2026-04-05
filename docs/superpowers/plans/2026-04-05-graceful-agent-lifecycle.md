# F-19: Graceful Agent Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable agents to cleanly shut down — generating work logs and learnings, then deregistering themselves — whether they finish all tasks or receive SIGTERM.

**Architecture:** A `SessionEnd` hook handles SIGTERM-initiated shutdown. The agent service's unregister method is updated to delete records (not just mark offline) and carry artifact paths. A consolidated cleanup script replaces three existing scripts. CLAUDE.md is updated with consolidation guidance.

**Tech Stack:** Python/FastAPI (backend), Bash (hook script, cleanup script), Shell (SIGTERM signaling)

**Important context:** All tasks for a worktree must be assigned before the agent starts working. The agent calls unregister when `get_my_tasks` returns empty — if tasks are assigned incrementally after launch, the agent may exit prematurely.

---

### Task 1: Backend — Add repository methods for worktree lookup and deletion

**Files:**
- Modify: `src/agent/repository.py`
- Test: `tests/agent/test_unit.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/agent/test_unit.py`:

```python
class TestAgentRepository:
    async def test_get_worktree_by_path(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        wt, _ = await repo.upsert_worktree(project.id, "/tmp/test-wt", "wt-test")
        found = await repo.get_worktree_by_path(project.id, "/tmp/test-wt")
        assert found is not None
        assert found.id == wt.id

    async def test_get_worktree_by_path_not_found(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        found = await repo.get_worktree_by_path(project.id, "/tmp/nonexistent")
        assert found is None

    async def test_delete_worktree(self, db_session: AsyncSession) -> None:
        project = await _create_project(db_session)
        repo = AgentRepository(db_session)
        wt, _ = await repo.upsert_worktree(project.id, "/tmp/test-del", "wt-del")
        session = await repo.create_session(wt.id)
        await repo.delete_worktree(wt.id)
        assert await repo.get_worktree(wt.id) is None
```

Note: Check if `_create_project` helper exists in the test file. If not, add one that creates a Project directly via the session.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_unit.py -k "TestAgentRepository" -v`
Expected: FAIL — methods don't exist.

- [ ] **Step 3: Implement repository methods**

In `src/agent/repository.py`, add two methods:

```python
    async def get_worktree_by_path(
        self, project_id: UUID, worktree_path: str
    ) -> Worktree | None:
        result = await self._session.execute(
            select(Worktree).where(
                Worktree.project_id == project_id,
                Worktree.worktree_path == worktree_path,
            )
        )
        return result.scalar_one_or_none()

    async def delete_worktree(self, worktree_id: UUID) -> None:
        """Delete worktree and all associated sessions."""
        # Delete sessions first (FK constraint)
        await self._session.execute(
            select(Session).where(Session.worktree_id == worktree_id)
        )
        sessions = (
            await self._session.execute(
                select(Session).where(Session.worktree_id == worktree_id)
            )
        ).scalars().all()
        for s in sessions:
            await self._session.delete(s)

        worktree = await self._session.get(Worktree, worktree_id)
        if worktree is not None:
            await self._session.delete(worktree)

        await self._session.commit()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/agent/test_unit.py -k "TestAgentRepository" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/repository.py tests/agent/test_unit.py
git commit -m "feat(agent): add get_worktree_by_path and delete_worktree repository methods"
```

---

### Task 2: Backend — Update unregister to delete records and add unregister-by-path endpoint

**Files:**
- Modify: `src/agent/services.py`
- Modify: `src/agent/routes.py`
- Modify: `src/agent/schemas.py`
- Test: `tests/agent/test_integration.py`

- [ ] **Step 1: Add UnregisterByPathRequest schema**

In `src/agent/schemas.py`, add after `AddTaskNoteRequest`:

```python
class ArtifactPaths(BaseModel):
    work_log: str | None = None
    learnings: str | None = None


class UnregisterByPathRequest(BaseModel):
    worktree_path: str
    artifacts: ArtifactPaths | None = None
```

- [ ] **Step 2: Write failing tests**

Add to `tests/agent/test_integration.py`:

```python
async def test_unregister_deletes_worktree_record(client: AsyncClient):
    """Unregistering an agent deletes the worktree from the DB."""
    # Register an agent
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/tmp/test-unreg-del", "branch_name": "wt-del"},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert resp.status_code == 201
    worktree_id = resp.json()["worktree_id"]

    # Unregister
    resp = await client.post(f"/api/v1/agents/{worktree_id}/unregister")
    assert resp.status_code == 204

    # Verify worktree is gone from the project's worktree list
    resp = await client.get(f"/api/v1/projects/{PROJECT_ID}/worktrees")
    worktree_ids = [w["id"] for w in resp.json()]
    assert worktree_id not in worktree_ids


async def test_unregister_by_path(client: AsyncClient):
    """Unregister-by-path resolves worktree and deletes it."""
    # Register an agent
    resp = await client.post(
        "/api/v1/agents/register",
        json={"worktree_path": "/tmp/test-unreg-path", "branch_name": "wt-path"},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert resp.status_code == 201

    # Unregister by path with artifacts
    with patch("src.agent.routes.event_bus.publish", new_callable=AsyncMock) as mock_pub:
        resp = await client.post(
            "/api/v1/agents/unregister-by-path",
            json={
                "worktree_path": "/tmp/test-unreg-path",
                "artifacts": {
                    "work_log": "/tmp/test-unreg-path/shutdown-artifacts/work-log.md",
                    "learnings": "/tmp/test-unreg-path/shutdown-artifacts/learnings.md",
                },
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        assert resp.status_code == 204
        # Verify WORKTREE_OFFLINE event was emitted with artifacts
        mock_pub.assert_called()
        event = mock_pub.call_args[0][0]
        assert event.type == "worktree_offline"
        assert event.data["artifacts"]["work_log"] is not None


async def test_unregister_by_path_not_found(client: AsyncClient):
    """Unregister-by-path returns 404 for unknown path."""
    resp = await client.post(
        "/api/v1/agents/unregister-by-path",
        json={"worktree_path": "/tmp/nonexistent"},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert resp.status_code == 404
```

Note: Check existing test file for `API_KEY`, `PROJECT_ID` constants and `client` fixture pattern. The agent integration tests use an authenticated client. Add the `patch` and `AsyncMock` imports at the top if not already present.

- [ ] **Step 2b: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_integration.py -k "unregister" -v`
Expected: FAIL

- [ ] **Step 3: Update the unregister service method to delete**

In `src/agent/services.py`, modify the `unregister` method:

```python
    async def unregister(
        self, worktree_id: UUID, artifacts: dict[str, str | None] | None = None
    ) -> None:
        """End the active session and delete worktree record."""
        worktree = await self._repo.get_worktree(worktree_id)
        if worktree is None:
            raise ValueError(f"Worktree {worktree_id} not found")

        session = await self._repo.get_active_session(worktree_id)
        if session is not None:
            await self._repo.end_session(session.id)

        event_data: dict[str, object] = {
            "worktree_id": str(worktree_id),
            "worktree_path": worktree.worktree_path,
        }
        if artifacts is not None:
            event_data["artifacts"] = artifacts

        await event_bus.publish(
            Event(
                type=EventType.WORKTREE_OFFLINE,
                project_id=worktree.project_id,
                data=event_data,
            )
        )

        await self._repo.delete_worktree(worktree_id)
```

- [ ] **Step 4: Add unregister_by_path service method**

In `src/agent/services.py`, add after the `unregister` method:

```python
    async def unregister_by_path(
        self,
        project_id: UUID,
        worktree_path: str,
        artifacts: dict[str, str | None] | None = None,
    ) -> None:
        """Resolve worktree by path and unregister it."""
        worktree = await self._repo.get_worktree_by_path(
            project_id, worktree_path
        )
        if worktree is None:
            raise ValueError(f"Worktree not found for path: {worktree_path}")
        await self.unregister(worktree.id, artifacts=artifacts)
```

- [ ] **Step 5: Add unregister-by-path route**

In `src/agent/routes.py`, add the import for `UnregisterByPathRequest` in the imports section, then add the route before the existing unregister route:

```python
@router.post("/agents/unregister-by-path", status_code=204)
async def unregister_by_path(
    body: UnregisterByPathRequest, service: ServiceDep, project: CurrentProject
) -> None:
    artifacts = None
    if body.artifacts is not None:
        artifacts = {
            "work_log": body.artifacts.work_log,
            "learnings": body.artifacts.learnings,
        }
    try:
        await service.unregister_by_path(
            project.id, body.worktree_path, artifacts=artifacts
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
```

Note: This endpoint requires auth (`CurrentProject` dependency) because it needs the `project_id` to resolve the worktree.

- [ ] **Step 6: Update existing unregister route to pass through**

The existing unregister route at `POST /agents/{worktree_id}/unregister` already calls `service.unregister()` which now deletes. No route change needed — the service method was updated in Step 3.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/agent/ -v`
Expected: All pass

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All 151 pass. Some existing tests may need updating if they assert worktree is "offline" after unregister — it should now be gone entirely.

- [ ] **Step 9: Commit**

```bash
git add src/agent/schemas.py src/agent/services.py src/agent/routes.py tests/agent/
git commit -m "feat(agent): unregister deletes worktree record, add unregister-by-path endpoint"
```

---

### Task 3: SessionEnd hook script

**Files:**
- Create: `.claude/hooks/agent-shutdown.sh`
- Modify: `.claude/settings.json` (project-level, at `/home/sachin/code/cloglog/.claude/settings.json`)

- [ ] **Step 1: Create the hook script**

Create `.claude/hooks/agent-shutdown.sh`:

```bash
#!/bin/bash
# SessionEnd hook: generates shutdown artifacts and calls unregister for worktree agents.
# Only runs if cwd is inside a worktree directory.

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd')

# Fast exit: not a worktree agent
[[ "$CWD" == *"/.claude/worktrees/"* ]] || exit 0

WORKTREE_NAME=$(echo "$CWD" | grep -oP '\.claude/worktrees/\K[^/]+')
ARTIFACTS_DIR="${CWD}/shutdown-artifacts"
mkdir -p "$ARTIFACTS_DIR"

# --- Generate work log ---
{
  echo "# Work Log: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo "**Worktree:** ${WORKTREE_NAME}"
  echo ""
  echo "## Commits"
  echo '```'
  cd "$CWD" && git log --oneline main..HEAD 2>/dev/null || echo "(no commits)"
  echo '```'
  echo ""
  echo "## Files Changed"
  echo '```'
  cd "$CWD" && git diff --name-only main..HEAD 2>/dev/null || echo "(none)"
  echo '```'
  echo ""
  echo "## Pull Requests"
  BRANCH=$(cd "$CWD" && git branch --show-current 2>/dev/null)
  if [[ -n "$BRANCH" ]]; then
    gh pr list --head "$BRANCH" --json number,title,state,url 2>/dev/null || echo "[]"
  fi
} > "${ARTIFACTS_DIR}/work-log.md"

# --- Generate learnings template ---
{
  echo "# Learnings: ${WORKTREE_NAME}"
  echo ""
  echo "**Date:** $(date +%Y-%m-%d)"
  echo ""
  echo "## What Went Well"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Issues Encountered"
  echo ""
  echo "<!-- Fill in during consolidation -->"
  echo ""
  echo "## Suggestions for CLAUDE.md"
  echo ""
  echo "<!-- Fill in during consolidation -->"
} > "${ARTIFACTS_DIR}/learnings.md"

# --- Call unregister-by-path ---
# Read the API key from the environment or the MCP server config
API_KEY="${CLOGLOG_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
  # Try to read from MCP server env file
  API_KEY=$(grep CLOGLOG_API_KEY "${CWD}/.env" 2>/dev/null | cut -d= -f2 || true)
fi

if [[ -n "$API_KEY" ]]; then
  curl -s -X POST "http://localhost:8000/api/v1/agents/unregister-by-path" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${API_KEY}" \
    -d "{
      \"worktree_path\": \"${CWD}\",
      \"artifacts\": {
        \"work_log\": \"${ARTIFACTS_DIR}/work-log.md\",
        \"learnings\": \"${ARTIFACTS_DIR}/learnings.md\"
      }
    }" 2>/dev/null || true
fi

exit 0
```

- [ ] **Step 2: Make executable**

```bash
chmod +x .claude/hooks/agent-shutdown.sh
```

- [ ] **Step 3: Register in settings.json**

In `/home/sachin/code/cloglog/.claude/settings.json`, add a `SessionEnd` entry. The file currently has `PreToolUse` entries. Add alongside them:

```json
{
  "hooks": {
    "PreToolUse": [
      ...existing entries...
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/agent-shutdown.sh",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: Test the hook manually**

Create a test by simulating hook input:

```bash
echo '{"cwd": "/tmp/not-a-worktree", "session_id": "test", "exit_reason": "other"}' | .claude/hooks/agent-shutdown.sh
echo "Exit code: $?"  # Should be 0, no artifacts generated
```

```bash
# Test with a worktree-like path (won't call API since no key, but should generate files)
mkdir -p /tmp/test-hook/.claude/worktrees/wt-test
echo '{"cwd": "/tmp/test-hook/.claude/worktrees/wt-test", "session_id": "test", "exit_reason": "other"}' | .claude/hooks/agent-shutdown.sh
ls /tmp/test-hook/.claude/worktrees/wt-test/shutdown-artifacts/
# Should show: work-log.md  learnings.md
rm -rf /tmp/test-hook
```

- [ ] **Step 5: Commit**

```bash
git add .claude/hooks/agent-shutdown.sh .claude/settings.json
git commit -m "feat(agent): add SessionEnd hook for graceful shutdown with artifact generation"
```

---

### Task 4: Consolidated cleanup script

**Files:**
- Create: `scripts/manage-worktrees.sh`
- Delete: `scripts/remove-worktree.sh`
- Delete: `scripts/cleanup-wave.sh`
- Delete: `scripts/close-wave.sh`

- [ ] **Step 1: Create the consolidated script**

Create `scripts/manage-worktrees.sh`:

```bash
#!/bin/bash
set -euo pipefail

# Consolidated worktree management script.
# Replaces: remove-worktree.sh, cleanup-wave.sh, close-wave.sh
#
# Usage:
#   ./scripts/manage-worktrees.sh remove <worktree-name> [worktree-name...]
#   ./scripts/manage-worktrees.sh close <wave-name> <worktree-name> [worktree-name...]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MODE="${1:?Usage: $0 <remove|close> [wave-name] <worktree-name> [worktree-name...]}"
shift

if [[ "$MODE" == "close" ]]; then
  WAVE_NAME="${1:?Usage: $0 close <wave-name> <worktree-name> [worktree-name...]}"
  shift
fi

WORKTREES=("$@")
if [[ ${#WORKTREES[@]} -eq 0 ]]; then
  echo "Error: provide at least one worktree name"
  exit 1
fi

echo "═══════════════════════════════════════════════════"
echo "  Mode: ${MODE}"
[[ "$MODE" == "close" ]] && echo "  Wave: ${WAVE_NAME}"
echo "  Worktrees: ${WORKTREES[*]}"
echo "═══════════════════════════════════════════════════"
echo ""

# --- Close mode: generate wave work log ---
if [[ "$MODE" == "close" ]]; then
  DATE=$(date +%Y-%m-%d)
  LOG_FILE="${REPO_ROOT}/docs/superpowers/work-logs/${DATE}-${WAVE_NAME}.md"
  mkdir -p "$(dirname "$LOG_FILE")"

  echo "── Generating wave work log ──"
  {
    echo "# Work Log: ${WAVE_NAME}"
    echo ""
    echo "**Date:** ${DATE}"
    echo "**Worktrees:** ${WORKTREES[*]}"
    echo ""
    echo "## Summary of Work"
    echo ""

    for wt in "${WORKTREES[@]}"; do
      WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
      echo "### ${wt}"
      echo ""

      if [[ -d "$WT_DIR" ]]; then
        COMMITS=$(cd "$WT_DIR" && git log --oneline main..HEAD 2>/dev/null || echo "  (no commits)")
        echo "**Commits:**"
        echo '```'
        echo "$COMMITS"
        echo '```'
        echo ""

        FILES=$(cd "$WT_DIR" && git diff --name-only main..HEAD 2>/dev/null || echo "  (none)")
        echo "**Files changed:**"
        echo '```'
        echo "$FILES"
        echo '```'
      else
        echo "(worktree not found — may have been cleaned already)"
      fi

      PR_INFO=$(gh pr list --repo sachinkundu/cloglog --state merged --head "$wt" --json number,title,url --limit 1 2>/dev/null || echo "[]")
      PR_NUM=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['number'] if d else 'N/A')" 2>/dev/null || echo "N/A")
      PR_TITLE=$(echo "$PR_INFO" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title'] if d else 'N/A')" 2>/dev/null || echo "N/A")

      echo ""
      echo "**PR:** #${PR_NUM} — ${PR_TITLE}"
      echo ""
      echo "---"
      echo ""
    done
  } > "$LOG_FILE"
  echo "  Written to: $LOG_FILE"
  echo ""
fi

# --- Remove worktrees ---
echo "── Removing worktrees ──"
for wt in "${WORKTREES[@]}"; do
  WT_DIR="${REPO_ROOT}/.claude/worktrees/${wt}"
  if [[ -d "$WT_DIR" ]]; then
    echo "  Removing $wt..."
    git worktree remove --force "$WT_DIR" 2>/dev/null || echo "    Warning: could not remove $WT_DIR"
    git branch -D "$wt" 2>/dev/null && echo "    Deleted branch $wt" || echo "    Branch $wt not found"
  else
    echo "  Skipping $wt (not found at $WT_DIR)"
  fi
done
echo ""

# --- Clean remote branches ---
echo "── Cleaning remote branches ──"
for wt in "${WORKTREES[@]}"; do
  if git ls-remote --heads origin "$wt" 2>/dev/null | grep -q "$wt"; then
    MERGED=$(git branch -r --merged main 2>/dev/null | grep "origin/$wt" || true)
    if [[ -n "$MERGED" ]]; then
      echo "  Deleting merged remote branch: $wt"
      git push origin --delete "$wt" 2>/dev/null || echo "    Warning: could not delete"
    else
      echo "  Remote $wt exists but NOT merged — skipping"
    fi
  else
    echo "  Remote $wt already gone"
  fi
done
echo ""

# --- Close mode: update main ---
if [[ "$MODE" == "close" ]]; then
  echo "── Updating main ──"
  git checkout main 2>/dev/null || true
  git pull origin main 2>/dev/null || true
  echo ""
fi

# --- Summary ---
echo "═══════════════════════════════════════════════════"
echo "  Done."
if [[ "$MODE" == "close" ]]; then
  echo "  Wave work log: ${LOG_FILE}"
  echo "  Next: review work log, update CLAUDE.md learnings, commit"
fi
echo "  Remaining worktrees:"
git worktree list
echo "═══════════════════════════════════════════════════"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/manage-worktrees.sh
```

- [ ] **Step 3: Delete old scripts**

```bash
rm scripts/remove-worktree.sh scripts/cleanup-wave.sh scripts/close-wave.sh
```

- [ ] **Step 4: Test the script**

```bash
# Verify help output
./scripts/manage-worktrees.sh 2>&1 | head -1
# Should show usage error

# Verify remove mode with non-existent worktree (should skip gracefully)
./scripts/manage-worktrees.sh remove nonexistent-wt-test
# Should print "Skipping nonexistent-wt-test (not found)"
```

- [ ] **Step 5: Commit**

```bash
git add scripts/manage-worktrees.sh
git rm scripts/remove-worktree.sh scripts/cleanup-wave.sh scripts/close-wave.sh
git commit -m "feat(scripts): consolidate 3 worktree scripts into manage-worktrees.sh"
```

---

### Task 5: Update CLAUDE.md with new workflow guidance

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Worktree Hygiene section**

In `CLAUDE.md`, find the "Worktree Hygiene" section and update references to old scripts. Replace any mention of `remove-worktree.sh`, `cleanup-wave.sh`, `close-wave.sh` with `manage-worktrees.sh`.

- [ ] **Step 2: Add Agent Shutdown section**

Add to the Agent Learnings section in CLAUDE.md:

```markdown
### Agent Shutdown
- **Agents deregister themselves.** When all tasks are complete (`get_my_tasks` returns empty), generate shutdown artifacts and call `unregister-by-path`. Never rely on the master agent or scripts to deregister.
- **All tasks must be assigned before launch.** The master agent must assign all tasks to a worktree before launching the agent. The agent exits when its task queue is empty — incremental assignment after launch risks premature exit.
- **SessionEnd hook handles SIGTERM.** If killed externally, the `.claude/hooks/agent-shutdown.sh` hook generates work logs and calls unregister automatically.
- **Artifact handoff is explicit.** The unregister call includes paths to `shutdown-artifacts/work-log.md` and `shutdown-artifacts/learnings.md`. The `WORKTREE_OFFLINE` event carries these paths for the main agent to consolidate.
- **Main agent consolidation.** On receiving `WORKTREE_OFFLINE` with artifacts: read the files, copy work log to `docs/superpowers/work-logs/`, merge learnings into CLAUDE.md, commit, then run `./scripts/manage-worktrees.sh remove {name}`.
```

- [ ] **Step 3: Update script references**

Find any reference to `scripts/create-worktree.sh` usage examples that mention old scripts and update them.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with graceful shutdown workflow and consolidated script"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full quality gate**

Run: `make lint && make typecheck && uv run pytest && cd frontend && npx vitest run`
Expected: All green

- [ ] **Step 2: Verify hook registration**

```bash
cat .claude/settings.json | python3 -m json.tool | grep -A5 SessionEnd
```
Expected: Shows the agent-shutdown.sh hook registered.

- [ ] **Step 3: Push**

```bash
git push origin HEAD
```
