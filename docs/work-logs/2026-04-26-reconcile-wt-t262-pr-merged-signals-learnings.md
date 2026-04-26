# Learnings: wt-t262-pr-merged-signals

**Date:** 2026-04-26

## What Went Well

- **Stdlib-only proofs are gold for protocol/schema demos.** The T-262 demo proved a Pydantic shape change without standing up Postgres. Each proof was an `import` + `assert` (or `ast` walk) wrapped in `uv run --quiet python - <<PY`, so `uvx showboat verify` ran hermetically on a clean host. Lifted directly from the T-290 demo pattern in this repo.
- **Backward-compat-first protocol design (Option A parallel map) reduced blast radius.** Keeping `tasks_completed` as a flat list and adding `prs` as a parallel key meant zero existing parsers needed to change. Consumers opt in when ready.
- **Codex's 5-session cap caught real gaps every round.** Each round surfaced a different propagation hole: (1) sibling instruction docs, (2) impossible API contract, (3) hand-built dict misses required field, (4) generated TS + impl-task block. Without the multi-round review, every one would have shipped broken. A demo passing locally is not the same as the protocol being implementable end-to-end.

## Issues Encountered

- **The codex 5-session cap is a hard ceiling — bundle the full propagation in round 1.** Each Codex round is a "session"; T-262 needed 5/5 because round 1 only updated the launch SKILL, then round 2 found the schema gap, round 3 found the hand-built dict, round 4 found the frontend types and impl-task block. If round 1 had grep'd every consumer of the old protocol/schema (skills + agents + templates + Pydantic models + hand-built dicts + generated frontend types) and bundled all of them, it could have been a 1-2 round PR. CLAUDE.md F-51 already calls this out for path allowlists; same lesson applies to protocol propagation.
- **`async def` route handlers are `AsyncFunctionDef` in `ast.walk`, not `FunctionDef`.** The first `bash docs/demos/.../demo-script.sh` run failed with `StopIteration` because the AST proof filtered for `ast.FunctionDef` and missed the async route. Pattern for route-handler inspection in any future demo: `isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))`.
- **Frontend type generation is an out-of-band step.** `docs/contracts/baseline.openapi.yaml` updates do NOT auto-regenerate `frontend/src/api/generated-types.ts`. The script `scripts/generate-contract-types.sh <abspath-to-contract>` must be invoked explicitly (and needs an absolute path — relative paths get re-anchored to `frontend/`). `make quality` does not catch the drift; only Codex did. **Suggest a follow-up task: add `make generate-types` or a check-types step to the quality gate that fails on drift.**

## Suggestions for CLAUDE.md

- **Pre-flight grep for "protocol propagation" tasks.** When changing an inbox event shape, MCP response shape, or any agent-instruction wording, grep for the old shape across:
  - `plugins/cloglog/skills/*/SKILL.md`
  - `plugins/cloglog/agents/*.md`
  - `plugins/cloglog/templates/*.md`
  - `plugins/cloglog/hooks/*.sh`
  - `src/agent/schemas.py` and `src/agent/services.py` (hand-built response dicts that bypass `model_validate`)
  - `docs/contracts/baseline.openapi.yaml` AND `frontend/src/api/generated-types.ts` (regenerate after contract edits)
  - `docs/design/agent-lifecycle.md`
  Bundle every hit in round 1 of any code review pass. Each missed hit costs one Codex session.
- **`from_attributes=True` Pydantic models hide a foot-gun.** Adding a required field to a model with `from_attributes=True` automatically works for callers that go through `Model.model_validate(orm_row)`, but silently breaks any caller that hand-builds the dict (`{"id": ..., "title": ...}`). Grep for hand-built dict patterns matching the model's field set whenever you add a required field.
