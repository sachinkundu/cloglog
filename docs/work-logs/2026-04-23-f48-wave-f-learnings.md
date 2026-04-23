# Learnings: wt-f48-wave-f (F-48 Wave F)

Observations surfaced during T-259/T-257/T-256/T-258 that other agents (or future me) should internalize. Each entry notes whether it belongs in `CLAUDE.md`, a memory file, a follow-up task, or just a one-time PR note.

## 1. Demo scripts must self-locate, not branch-locate

**Claim.** `docs/demos/<branch>/demo-script.sh` should derive `DEMO_DIR` from
its own location, not from `git rev-parse --abbrev-ref HEAD`. Codex flagged
this on PR #186 round 1: a derivation like `docs/demos/${BRANCH//\//-}-T-259`
silently drifts under branch rename (close-off branches, cherry-picks, forks).

**Concrete fix.** Use the three-liner established by T-259:

```bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DEMO_DIR="${SCRIPT_DIR#"$REPO_ROOT"/}"
```

Every T-256, T-257, T-258 demo I wrote after that uses this pattern.

**Where it belongs.** `plugins/cloglog/skills/demo/SKILL.md` — the "Backend /
API / CLI demo" template and the "Frontend / UI demo" template both currently
show `DEMO_FILE="docs/demos/${BRANCH//\//-}/demo.md"`. Swap them for the
SCRIPT_DIR-derived form. Suggested as a one-line follow-up against the skill
rather than bundled here, because it touches every agent that consumes the
template, not F-48 scope.

## 2. Demo `exec` bash strings must not contain backticks or unescaped `$VAR`

**Claim.** I hit this in both T-257 and T-258 demos. Showboat `exec` gets
a bash string; inside the OUTER double-quoted showboat `note` or `exec` arg,
`` `foo` `` runs `foo` as command substitution (ImageMagick's `import` hung
the whole T-259 demo for 10+ minutes with `import yaml` as its argv), and
`"$VAR"` expands at outer-shell time even if you want it to expand inside
the stub being written.

**Fixes.**
- For showboat `note` arguments that contain backticks or `$`, use SINGLE quotes
  around the outer arg so nothing expands. My T-258 demo did this for Proof 5.
- For `printf` writes that assemble a shim script, escape with `\$` so the
  dollar reaches the generated file verbatim (T-257 demo's stub `npm`).
- Set `$VAR` before the printf if you want the outer shell's value baked in.

**Where it belongs.** Same SKILL.md update — add a "Quoting pitfalls" section
to the "Determinism" note. Not CLAUDE.md because it's content-specific guidance
for showboat, not a project-wide rule.

## 3. `make quality`'s `demo-check` picks the alphabetically-first matching dir

**Claim.** `scripts/check-demo.sh` walks `docs/demos/*/` and `break`s on the
first match whose name contains the branch name. In a worktree that ships
multiple sequential PRs under the same branch (this worktree: T-259/T-257/
T-256/T-258), the alphabetical winner is not necessarily the CURRENT PR's
demo. For my T-258 PR, the gate picked `wt-f48-wave-f-T-256/` first and
verified THAT demo, not the T-258 one I just wrote.

**Mitigation I used.** `DEMO_FEATURE=wt-f48-wave-f-T-258 make quality`
forces the gate onto the specific dir. Both default and targeted runs
pass on my PR because each demo is independently deterministic, but the
gate does NOT pin the current-PR's demo specifically.

**Actual failure mode to watch for.** If the CURRENT PR's demo breaks
(e.g., deterministic output drift) but an earlier merged demo still
verifies, `make quality` passes and the broken demo ships. The fix
would be `check-demo.sh` preferring the dir that was modified in
`git diff main..HEAD` (scope-specific) before falling back to
alphabetical substring. Filing as a follow-up task idea, not included
in this wave because it's cross-cutting tooling work.

## 4. Middleware presence-check ≠ per-route value-check

**Claim.** `ApiAccessControlMiddleware` in `src/gateway/app.py` only checks
that a credential header is PRESENT on non-agent routes. It does NOT
validate the bearer value. Token-value validation is the per-route
`Depends(CurrentMcpService)` / `Depends(CurrentMcpOrDashboard)` job, and
routes that forget to declare one silently accept any bearer under the
MCP shape. Codex caught this on PR #191 round 2 for `list_worktrees`.

**Where it belongs.** This is already documented in `src/gateway/app.py`'s
middleware comments and in `docs/ddd-context-map.md § Auth Contract` (which
I added in T-258). Worth a CLAUDE.md mention under "Cross-Context
Integration" because it has now bitten at least twice — the `/api/v1/agents/*`
permissive-auth bucket note from a prior round, and now this
`list_worktrees` case. Suggested text:

> "Every non-agent route that accepts MCP credentials MUST declare
> `CurrentMcpService` or `CurrentMcpOrDashboard` as a `Depends`.
> Middleware presence-checks the headers but does not validate the bearer.
> A new non-agent route added without the dep is silently open to any
> bearer under `X-MCP-Request: true`. Add a regression test named
> `test_*_rejects_invalid_mcp_bearer` that asserts 401 for garbage bearer
> + X-MCP-Request."

Adding this as a CLAUDE.md item is the highest-leverage learning from
Wave F — the security hole was dormant for months before codex spotted it.

## 5. `_auth_headers`-style helpers conflate param naming and caller
ownership

**Claim.** `src/gateway/cli.py::_auth_headers(api_key)` takes an `api_key`
parameter and sends it as `X-Dashboard-Key`. Pre-T-258 callers passed
whatever Typer read from `CLOGLOG_API_KEY` — Typer's envvar-passthrough
convention plus the helper's semantic-blind name meant a missing env var
silently produced empty headers, which the middleware rejected with a
cryptic 401. The user and reviewers can't tell by reading the code what
the contract is.

**Fix used.** `_require_dashboard_key(api_key, operation)` that exits 1
locally with the operation name + env var + doc link. Every command that
hits a non-agent route now calls it at the top.

**Where it belongs.** Per-PR note only. The pattern is captured in the
T-258 Auth Contract docs and codified in the regression tests. Not a
CLAUDE.md rule — it's a local-code-review smell, not a systemic
invariant.

## 6. `tail -F` for inbox monitors, not `tail -f`

**Claim.** My initial Monitor command `tail -f .cloglog/inbox` failed
because the inbox file didn't exist yet. Switched to `tail -F` (capital F,
follow by name with retry) so the monitor survives file creation / rename /
rotation.

**Where it belongs.** `plugins/cloglog/skills/launch/SKILL.md` — the
Monitor invocation example should use `tail -F` (or `touch` the inbox
first). One-line fix. Suggested as a follow-up task.

## 7. Cross-agent conflict guard works end-to-end

**Claim.** The AGENT_PROMPT's cross-agent conflict block worked exactly
as specified. T-258 targeted `src/gateway/app.py` + `docs/ddd-context-map.md`;
PR #187 (wt-f47-two-stage-review) was OPEN against both. Emitted
`mcp_tool_error` with `reason: cross_agent_file_conflict`; main agent
acknowledged with `resume_instruction`; waited for forwarded
`pr_merged`; resumed with clean rebase.

**Subtle learning.** The main agent FORWARDED the `pr_merged` event
because wt-f47's agent had already exited — the backend's webhook
consumer only routes to the active agent, so a later-starting agent on
the same topic can miss the original event. Keeping the
`resume_instruction` pattern + main-agent forwarding is load-bearing.

**Where it belongs.** Worth a short note in `docs/design/agent-lifecycle.md`
§4 about cross-agent coordination. Not urgent — the mechanism already
works; just a documentation gap.

## 8. `tests/gateway/test_cli.py` needed `--api-key` on every mocked command

**Claim.** Before T-258, CLI commands that hit non-agent routes worked
in tests because respx mocked the endpoints and never exercised the
middleware. After T-258 added `_require_dashboard_key` at the CLI
layer, those tests failed fast LOCALLY (guard exits before HTTP).
Updated 13 test invocations to pass `--api-key "test-key"`; no runtime
behavior changed.

**Where it belongs.** PR note only. The tests now self-document — each
updated invocation has a comment citing T-258 / codex round 1.

---

## Follow-up tasks suggested (not filed — leaving to main agent)

1. **SKILL.md template refresh** — swap the demo-path derivation in
   `plugins/cloglog/skills/demo/SKILL.md` from branch-based to
   SCRIPT_DIR-based (Learning 1). Add a "Quoting pitfalls" section
   (Learning 2). Update `launch/SKILL.md` Monitor example to use
   `tail -F` (Learning 6).
2. **CLAUDE.md rule** — "Every non-agent route accepting MCP credentials
   MUST declare CurrentMcpService/CurrentMcpOrDashboard as Depends"
   (Learning 4). Highest-leverage of the batch; a dormant security hole
   just got closed.
3. **`check-demo.sh` scope-aware picking** — prefer demos under dirs
   modified in `git diff main..HEAD` over alphabetical substring match
   (Learning 3). Cross-cutting tooling work, likely its own small task.
4. **Tasks-CLI dashboard-key ergonomics** — `tasks_show`, `tasks_unassign`,
   `tasks_start`, `tasks_complete`, `tasks_set_status` also hit
   non-agent routes without declaring `--api-key` or calling the guard;
   they'd emit a remote 401 today. Out of T-258 scope but a clean
   bundled PR if someone wants it.
5. **Shared WORK-dir across demo runs** — `docs/demos/wt-c2-mcp-rebuild/`
   still uses `WORK="${TMPDIR:-/tmp}/t244-demo"` (shared root). Port-0
   fixes port collisions but not filesystem collisions. Separate concern,
   flagged in T-256 codex round 2.
