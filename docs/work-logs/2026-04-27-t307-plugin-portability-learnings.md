# Learnings — T-307 Plugin Portability Audit

Durable, non-obvious gotchas worth folding into CLAUDE.md.

## Codex review of design docs

- **Codex 5/5 cap is not optional ceiling on factual-precision PRs.** A research/audit doc that cites file:line evidence will burn codex sessions on every imprecision (wrong path, stale reference, mis-scoped finding) — each round generates new sibling findings as codex re-reads adjacent files. Bundling the entire scope correctly in round 1 is the only way to stay under the cap. Once exhausted, the PR is operator-driven; codex skips with a "request human review" comment.
- **`gitignored` ≠ "not a leak".** The audit initially flagged `.cloglog/launch.sh` as a tracked leak; codex 1/5 caught it (already in `.gitignore:17`). The correct framing is *runtime contents* — even gitignored files can embed operator-host absolute paths that break when copied between operators. Distinguish "tracked leak" from "host-specific runtime state" in audit findings.
- **Client-side preflights vs. safety boundaries.** `enforce-task-transitions.sh` looks like a guard, but the backend already blocks agent → `done` at `src/agent/services.py:417` and `:501`. Skipping the hook is a UX/portability degradation, not a safety bypass. Audit findings about hooks should distinguish preflight UX from authoritative enforcement — codex will catch the inversion.

## YAML config parsing in plugin hooks

- **`python3 -c 'import yaml'` violates the project's own invariant (`docs/invariants.md:76`).** Five plugin entry points still do this — `worktree-create.sh:35-41`, `quality-gate.sh:39-43`, `protect-worktree-writes.sh:52-72`, `enforce-task-transitions.sh:50-56`, `launch/SKILL.md:223-229` (template materialised into `.cloglog/launch.sh`). On hosts without global PyYAML the worktree never registers, the scope guard drops, and unregister-by-path posts to the wrong backend. Fix is mechanical for the four scalar-key parsers (grep+sed pattern from `.cloglog/on-worktree-create.sh:88-105`); `protect-worktree-writes.sh` reads the **nested `worktree_scopes` mapping** that grep+sed cannot represent — it needs a plugin-shipped Python parser or a flatter config format. **Don't call YAML-parser cleanup "mechanical" without checking each parser's nesting depth.**

## Audit doc structure & operator direction

- **Preserve the original evidence trail when operator direction overrides recommendations.** When the operator sets a new policy mid-review (e.g., "shared bots, no per-project Apps"), the right move is *not* to rewrite findings in place — strikethrough + Resolved annotation + a preamble carrying the override preserves the audit value while making the new direction authoritative. Codex's findings remain readable for downstream onboarding work.
- **Open Questions section is high-value when operator direction is mid-flight.** Resolved-question marks-for-posterity ("~~Plugin install model~~ → local-folder for now; marketplace later.") prevent future re-debate of decisions the operator already made. Keep them in the doc; don't delete.
