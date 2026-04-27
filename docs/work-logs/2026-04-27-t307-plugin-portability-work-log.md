# Work log — T-307 Plugin Portability Audit

**Worktree:** wt-t307-plugin-portability-audit
**Branch:** wt-t307-plugin-portability-audit
**PR:** https://github.com/sachinkundu/cloglog/pull/232 (merged)
**Task:** T-307 (F-52)

## Deliverable

`docs/design/plugin-portability-audit.md` — a research/design doc cataloguing every place the cloglog plugin (`plugins/cloglog/`) and its surrounding machinery (`mcp-server/`, `.cloglog/`, `scripts/`, root docs) is implicitly bound to the cloglog repo itself when the product premise is `/cloglog init` should onboard *any* project.

Doc structure:
- Executive summary — top 6 friction points ranked by adoption blast radius (Phase 0 = YAML-parser hook bug, then placeholders/branding/skill-cites/runtime-artefacts).
- Findings by category — file:line tables across plugin, MCP server, backend, runtime, skills, init flow, docs, tests, GitHub App story.
- Onboarding walkthrough — step-by-step trace of `/cloglog init` on a fresh repo with every error/prompt verbatim.
- Recommended sequence — Phase 0 → Phase 3 fix ordering, parallelisable lanes, smallest "first new project onboarded" milestone.
- Open questions — pruned to 4 after operator direction (marketplace timing, codex prompt customisation surface, multi-project credential format, `mcp__cloglog__*` rename).
- User direction (2026-04-27) preamble — operator overrides applied to the audit (shared bots, :8001 default, no agent-vm yet, etc.).

## Iteration history

7 commits across 2 sessions:
- dc3568f — initial audit doc
- 3c4e084 — codex 1/5 corrections (launch.sh framing, on-worktree-create failure mode, test grep)
- a7581f6 — codex 2/5 (demo-allowlist row + YAML-parser hook finding promoted to Phase 0)
- 68fdec4 — codex 3/5 (fourth `import yaml` hook in enforce-task-transitions, launch.sh shutdown path, smoke-test scoping)
- be33acc — codex 4/5 (alignment with installed-plugin design contract; on-worktree-create per-project opt-ins)
- a47608f — codex 5/5 (enforce-task-transitions impact reframed as client-side preflight; YAML-parser cleanup nuance for nested scopes; init Step ordering)
- 8170a2e — operator direction (2026-04-27): shared bots, :8001 default, agent-vm staleness, etc.

Codex 5/5 cap exhausted before approval; final review was operator-driven.

## Verification

- `make quality` PASSED end-to-end on the final SHA (54 review tests, 911 backend tests, 88.4% coverage, contract compliant, docs-only demo exempt, MCP server tests green).
- Demo classifier auto-exempted (docs-only branch).
- PR merged by operator after applying 2026-04-27 direction preamble.

## Follow-ups (filed implicitly via the audit; not created on the board this session)

The audit's Recommended Sequence enumerates the concrete fix tasks. Phase 0 (YAML-parser hooks) is the unblock-everything prerequisite; Phase 1 hardens plugin install path; Phase 2 makes `/cloglog init` produce a runnable project; Phase 3 adds pin tests + CI smoke. Phase 3 (multi-tenant Apps) was dropped per operator direction.
