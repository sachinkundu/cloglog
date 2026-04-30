# Wave: F-46 Agent Lifecycle Hardening (2026-04-30)

Bundle of four PRs against `plugins/cloglog/skills/launch/SKILL.md` and adjacent surfaces — all four address gaps observed during this same session's launch attempts. Land order: T-353 → T-356 → T-358 → T-360.

## Worktrees

### wt-t353-launch-quoted-heredoc — PR #276

**Title:** fix(launch): quoted heredoc for launch.sh emission (T-353)
**Commits:**
- `5dd6bb1` feat: quoted heredoc for launch.sh emission (T-353)
- `b283155` fix(launch): escape sed replacement for paths containing & | \  *(codex round 1)*

**Files changed:**
- `CLAUDE.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `tests/plugins/test_launch_skill_exports_gh_app_env.py`
- `tests/plugins/test_launch_skill_renders_clean_launch_sh.py`
- `tests/plugins/test_no_python_yaml_in_scalar_hooks.py`

### wt-t356-launch-confirm-timeout — PR #277

**Title:** feat(launch): agent_started timeout + operator alert (T-356)
**Commits:**
- `507a27f` feat(launch): agent_started timeout + operator alert (T-356)
- `4da538f` fix: address codex round 1 findings (T-356)

**Files changed:**
- `.cloglog/config.yaml`
- `CLAUDE.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `plugins/cloglog/skills/setup/SKILL.md`
- `tests/plugins/test_launch_skill_has_agent_started_timeout.py`

### wt-t358-narrow-toasts — PR #278

**Title:** feat(gateway): narrow desktop toasts to operator-attention events (T-358)
**Commits:**
- `7b1aa0e` feat(gateway): narrow desktop toasts to operator-attention events (T-358)
- `035c650` fix(gateway): cut unwired toast classes; gate AGENT_UNREGISTERED on non-clean reasons (T-358 codex round 1)

**Files changed:**
- `.cloglog/config.yaml`
- `CLAUDE.md`
- `docs/demos/wt-t358-narrow-toasts/{demo-script.sh,demo.md}`
- `src/agent/services.py`
- `src/gateway/notification_listener.py`
- `src/shared/events.py`
- `tests/gateway/test_notification_listener.py`
- `tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py`
- `tests/gateway/test_notification_listener_toasts_on_unregister_filter.py`

### wt-t360-prompt-template — PR #279

**Title:** feat(launch): AGENT_PROMPT.md template + per-task task.md (T-360)
**Commits (8):** initial + 5 codex fix rounds + merge from origin/main + exemption refresh.
- `e6cb57b` feat(launch): AGENT_PROMPT.md template + per-task task.md (T-360)
- `5dac4f2` fix(launch): explicit register_agent + get_my_tasks defense (codex round 1)
- `b788d35` fix(launch): pipeline-aware task resolution + sed escape (codex round 2)
- `34fbf28` fix(launch): complete multi-line task.md substitution + worktree-agent.md drift (codex round 3)
- `5c14336` fix(launch): drop unsupported workflow_override + task_type fallback (codex round 4)
- `cf54f58` fix(launch): single task-resolution contract + drop workflow_override leftover (codex round 5)
- `18cfe33` Merge remote-tracking branch 'origin/main' (resolve conflict with T-353 SKILL changes)
- `a36c23f` chore(demo): refresh exemption hash post-merge

**Files changed:**
- `.gitignore`
- `CLAUDE.md`
- `docs/demos/wt-t360-prompt-template/exemption.md`
- `plugins/cloglog/agents/worktree-agent.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `plugins/cloglog/skills/setup/SKILL.md`
- `plugins/cloglog/templates/AGENT_PROMPT.md` *(new)*
- `tests/plugins/test_agent_prompt_template_correct_inbox_paths.py`
- `tests/plugins/test_agent_prompt_template_no_workflow_override_recurrence.py`
- `tests/plugins/test_launch_skill_renders_template_and_task_md.py`
- `tests/plugins/test_plugin_search_guidance.py`
- `tests/plugins/test_worktree_agent_md_points_at_task_md.py`
- `tests/test_agent_lifecycle_pr_signals.py`
- `tests/test_mcp_failure_rule_wording.py`

## Shutdown summary

| Worktree | PR | Shutdown path | Commits |
|---|---|---|---|
| wt-t353-launch-quoted-heredoc | #276 | cooperative (auto, before close-wave) | 2 |
| wt-t356-launch-confirm-timeout | #277 | cooperative (auto, before close-wave) | 2 |
| wt-t358-narrow-toasts | #278 | cooperative (auto, before close-wave) | 2 |
| wt-t360-prompt-template | #279 | cooperative (auto, before close-wave) | 8 |

All four agents emitted `agent_unregistered` (`reason: pr_merged`) before close-wave ran — no `request_shutdown` was needed. Tabs were closed during Step 6 to terminate the surviving claude REPL processes (see Learnings).

## Per-task work logs (consolidated)

_Inlined below in Step 5d._

## Learnings & Issues

### Postman work the operator had to do this wave

The four hand-built AGENT_PROMPTs all said "Monitor your inbox at `/home/sachin/code/cloglog/.cloglog/inbox`" (project root). The launch SKILL's intended convention is that agents tail their **worktree** inbox; the project root inbox is for cross-agent / supervisor traffic. Backend webhook fan-out for `review_submitted` writes to the worktree inbox. Result: agents never saw codex review events delivered by the backend; the operator manually `tail -1 worktree/inbox >> project-root/inbox` for every codex round across three PRs. Roughly ten manual forwards over the wave.

T-360 ships the structural fix (a single `plugins/cloglog/templates/AGENT_PROMPT.md` that any future launch copies; per-task content lives in a small `task.md`). Once the next wave launches via the new template, this class of bug is gone.

### Hung claude processes after clean unregister (Step 6)

All four agents emitted `agent_unregistered` cleanly and the backend rows were torn down — but the claude REPL processes themselves remained running, idle at their prompts. Closing the zellij tabs via `zellij action go-to-tab-name <wt> && close-tab` triggered launch.sh's `trap '_on_signal HUP' HUP` which gracefully killed claude. This means the §2 shutdown protocol terminates *backend state* but does not terminate the *agent process*. The right fix is the agent calling `exit` after `unregister_agent` — which the launch SKILL prompt template already says, but the worktree-agent template that T-360 ships will canonicalize.

### Codex 5/5 cap caught T-360 after a 5-round + rebase cycle

T-360's PR went through five codex rounds (initial → 4 fix rounds), then hit a merge conflict because T-353 had merged first. After rebase, codex round 5 returned `:warning:` not `:pass:`, hitting the 5/5 cap. Operator merged manually after assessing the remaining MEDIUM findings (continuation-session inconsistency; a secondary `worktree-agent.md` doc still mentioned `workflow_override`). For PRs with rebase rounds + many codex rounds, the cap is a real ceiling — bundle scope correctly in round 1.

### PR merge conflicts have no event signal

When T-353 merged, T-360 transitioned to `mergeable: CONFLICTING / mergeStateStatus: DIRTY`. No inbox event fired. The agent waited passively for `pr_merged` that would never come. Operator had to notice manually 30+ minutes later. Filed as **T-362** (next wave): backend should translate `pull_request.synchronize` for main + a 60s mergeable-state poll into a `pr_conflict_detected` event; AGENT_PROMPT template adds a `git fetch && git rebase origin/main` handler.

### Inbox-truncate before close-wave

The `tests/plugins/test_launch_skill_exports_gh_app_env.py::test_no_operator_host_literals_in_plugin_or_tracked_cloglog_dir` pin scans every file under `.cloglog/` for App ID/Installation ID literals. The operator instruction sent during this wave (to unblock T-356 with credentials) included the literal IDs in plaintext in the inbox. Quality gate caught it. Truncating `.cloglog/inbox` before the close-wave quality gate is the correct posture — agents are gone, events are processed, runtime state is disposable.

This raises an architectural point: the pin scans gitignored runtime files (the inbox), not just tracked files. That's a feature, not a bug — runtime files can leak via close-wave artifacts if archived. But the operator must never type these literals into operator_instruction events; reference them via env vars or local.yaml only.

### `agent_blocked` shape vs. operator-message shape

When T-356 emitted `agent_blocked: gh_app_credentials_missing`, the operator's first nudge used `{"type":"retry"}` which the agent didn't pattern-match against any documented event class. The second nudge used `{"type":"operator_instruction"}` which worked. The launch SKILL / AGENT_PROMPT template should formalize the operator → agent message shape (e.g. `operator_instruction` with a free-text `instruction` field) as a documented event class — same way `pr_merged`, `review_submitted`, `agent_blocked` are documented.

## State After This Wave

- `plugins/cloglog/skills/launch/SKILL.md`: emits launch.sh via quoted heredoc + sed substitution (T-353); confirms agent_started with a 90s deadline + diagnostic checklist (T-356); writes `AGENT_PROMPT.md` (template copy) + per-task `task.md` (T-360).
- `plugins/cloglog/templates/AGENT_PROMPT.md` (new, T-360): single source of truth for worktree-agent workflow.
- `src/gateway/notification_listener.py`: desktop toasts narrowed to `agent_unregistered` with non-clean `reason` (T-358) — routine review transitions no longer toast.
- `.cloglog/config.yaml`: new keys `launch_confirm_timeout_seconds: 90` (T-356), `desktop_toast_enabled: true` (T-358).
- New CLAUDE.md learnings: heredoc escaping under LLM-tool boundaries; agent_started liveness deadline; desktop-toast operator-attention rule; workflow-rules-in-template.
- F-46 follow-ups still pending: T-354 (static template refactor — replaces heredoc entirely with `cp` over `.template`); T-362 (PR merge conflict event + rebase handler).

---
_From wt-t353-launch-quoted-heredoc/shutdown-artifacts/work-log-T-353.md:_

---
task: T-353
task_id: 26e279ac-c893-4d70-8c68-cc115deb88a3
feature: F-46
worktree: wt-t353-launch-quoted-heredoc
worktree_id: a4d8f3dd-d0f4-4254-b1d2-f337a7796657
pr: https://github.com/sachinkundu/cloglog/pull/276
pr_number: 276
merged_at: 2026-04-30T06:52:08Z
merge_commit: e9176a3f394e781335db9a96eb3cbcb34a9b9487
---

# T-353 — launch.sh write-time fragility: quoted heredoc fix

## What shipped

- `plugins/cloglog/skills/launch/SKILL.md` — switched the `cat > .../launch.sh << EOF` emitter to a quoted heredoc (`<< 'EOF'`) so bash performs zero expansion inside. Removed every `\$`, `\\`, `\"` from the helper bodies. Replaced the two operator-host-specific values (`WORKTREE_PATH`, `PROJECT_ROOT`) with `@@WORKTREE_PATH@@` / `@@PROJECT_ROOT@@` placeholders, then bake them in via post-render `sed -i "s|@@...@@|...|g"`.
- `_sed_escape_replacement` helper (codex round 1 fix) — backslash-escapes `&`, `|`, and `\` in the path before substitution so that legal host paths under `~/R&D/` etc. don't get corrupted. `&` in a sed replacement expands to the matched text; without escaping, `fake&wt` would render as `fake@@WORKTREE_PATH@@wt`.
- `tests/plugins/test_launch_skill_renders_clean_launch_sh.py` — new pin: extracts the emit block from SKILL.md, materialises it against fixture paths containing `&` (`fake&wt` / `fake&proj`), then asserts (1) `bash -n` passes, (2) the exact helper-arg lines that broke in antisocial are present (`local file="$1"; local key="$2"`, `local sig="$1"`, `local sig="${1:-unknown}"`), (3) sed substitutions land, (4) no `\$` antipattern remains, (5) no leftover `@@...@@` placeholders. Second test pins SKILL.md text-level: must contain quoted-EOF opener, must not contain unquoted form.
- Updated existing pins (`test_launch_skill_exports_gh_app_env`, `test_no_python_yaml_in_scalar_hooks`) to accept either heredoc form.
- `CLAUDE.md` — extended the "Templating shell into shell via unquoted heredoc multiplies escaping" entry under **Plugin hooks: YAML parsing** with the quoted-heredoc rule + the `unexpected EOF while looking for matching '"'` grep token.

## Why it shipped

Observed in antisocial 2026-04-30: a worktree agent's `.cloglog/launch.sh` failed at exec time with `unexpected EOF while looking for matching '"'`. The rendered helper bodies were mangled (`local file="\"; local key="\"`, `local sig="\"`) — the `$1`/`$2` positional-arg references inside helper functions had been stripped, leaving unterminated strings. Root cause: the SKILL emitted launch.sh through an unquoted heredoc with `\$1` / `\$2` escapes; across the SKILL → LLM-agent Bash-tool → bash boundary the `\$N` escapes collapse inconsistently.

T-353 is the minimum-viable escaping fix. The architectural followup (replace the heredoc with a static template file + `cp` + `sed`) is filed as **T-354**.

## Codex review

- Round 1: HIGH — `sed` replacement metacharacters (`&`, `|`, `\`) interpreted inside the replacement string would corrupt paths like `~/R&D/...`. Fixed via `_sed_escape_replacement` helper. Pin extended with `&` in fixture paths.
- Round 2: `:pass:`. Auto-merge gate returned `merge`; squash-merged.

## Residual TODOs / context the next task should know

- **T-354** is the architectural followup: replace the in-SKILL heredoc with a static template file at `plugins/cloglog/templates/launch.sh.template` and `cp .template + sed` in the SKILL. The template is then a normal tracked bash file that lints/edits like any other. T-353's quoted-heredoc fix is the prerequisite — T-354 removes the heredoc-templating boundary entirely. The codex round-2 review of T-353 explicitly endorsed deferring this to T-354.
- The `_sed_escape_replacement` helper added in this PR uses `sed 's/[\\&|]/\\&/g'` (matches `plugins/cloglog/skills/launch/SKILL.md:107-109` and the T-360 task.md renderer). T-354 will inherit the same escape concern — when the static template is materialised via `cp` + `sed`, the same replacement-string metacharacters need escaping. The helper shape is the canonical form; do not reinvent it.
- The pin test's `_extract_emit_block` extractor was widened to capture all post-heredoc lines through `chmod +x` so that the `_sed_escape_replacement` setup runs alongside the `sed -i` calls during fixture rendering. T-354 may further restructure this — keep the extractor "everything between `EOF` and `chmod +x`" logic in mind.
- One pre-existing pin (`tests/plugins/test_plugin_docs_self_contained.py::test_no_bare_setup_credentials_path_in_plugin`) requires the literal substring `${CLAUDE_PLUGIN_ROOT}/docs/setup-credentials.md` in the SKILL. Inside the now-quoted heredoc, `${CLAUDE_PLUGIN_ROOT}` no longer expands at write time — it appears verbatim in rendered launch.sh comments. That's fine (only a comment), but T-354 should be aware: any restructure that drops the literal token will fail the docs-self-contained pin.

## Files changed

- `CLAUDE.md`
- `plugins/cloglog/skills/launch/SKILL.md`
- `tests/plugins/test_launch_skill_exports_gh_app_env.py`
- `tests/plugins/test_launch_skill_renders_clean_launch_sh.py` (new)
- `tests/plugins/test_no_python_yaml_in_scalar_hooks.py`

## Verification

- `make quality` PASSED locally on both rounds (1140 → 1140 passed, 1 skipped, 1 xfailed).
- `pytest tests/plugins/test_launch_skill_renders_clean_launch_sh.py` — 2 passed.
- Manual sanity render with `WORKTREE_PATH=/tmp/.../fake&wt PROJECT_ROOT=/tmp/.../fake&proj` produced clean launch.sh; `bash -n` succeeds.
- CI (ci, e2e-browser, init-smoke) all green at merge time.

---
_From wt-t356-launch-confirm-timeout/shutdown-artifacts/work-log-T-356.md:_

---
task: T-356
task_id: 7c5ee7af-4b51-4cdb-ac54-f5ef564090ea
title: Main agent must detect failed launches — agent_started timeout + operator alert
feature: F-46 Agent Lifecycle Hardening — Graceful Shutdown & MCP Discipline
worktree: wt-t356-launch-confirm-timeout
worktree_id: e45f014b-44b2-401d-bf6b-de150ff37b9a
pr: https://github.com/sachinkundu/cloglog/pull/277
pr_number: 277
merged_at: 2026-04-30T06:01:57Z
---

## What shipped

Plugin-skill prose change to enforce a launch-confirmation deadline on both initial launches and supervisor relaunches. The spawned-zellij-tab heuristic was the only liveness signal before — a tab can hold a crashed `claude`, a heredoc-rendered `launch.sh` with `unexpected EOF` (T-353 class), a half-applied `on-worktree-create.sh`, an MCP-unavailable abort, etc., and `query-tab-names` will still list it. The main agent then sat optimistically on review/merge events that would never arrive, and only the operator noticed.

The new contract: per spawned worktree, watch `<project_root>/.cloglog/inbox` for an `agent_started` event whose `worktree` field matches, with a `launch_confirm_timeout_seconds` deadline (default 90s, configurable). On timeout, emit a 5-item diagnostic checklist (`zellij action query-tab-names | grep`, `bash -n <worktree>/.cloglog/launch.sh`, `tail -20 /tmp/agent-shutdown-debug.log`, split-credentials probe, `head -3 launch.sh`) and hand off to the operator. **No silent retry.** Same contract on both call sites:

1. **Initial launch** — `plugins/cloglog/skills/launch/SKILL.md` Step 5 (Verification).
2. **Supervisor relaunches between tasks** — `plugins/cloglog/skills/launch/SKILL.md` Supervisor Relaunch Flow + `plugins/cloglog/skills/setup/SKILL.md` Handle agent_unregistered. Both must enforce the same deadline; the round-1 codex review caught the setup SKILL drifting and demanded the mirror.

## Files touched

- `plugins/cloglog/skills/launch/SKILL.md` — Step 5 + Supervisor Relaunch Flow (deadline + checklist + no-silent-retry).
- `plugins/cloglog/skills/setup/SKILL.md` — Handle agent_unregistered Step 4 (mirrors launch SKILL contract).
- `.cloglog/config.yaml` — `launch_confirm_timeout_seconds: 90` with comment.
- `CLAUDE.md` — new "Inbox monitor" entry capturing the symptom (silent stuck-waiting + no `agent_started`) and the rule.
- `tests/plugins/test_launch_skill_has_agent_started_timeout.py` — 5 pin cases:
  - Step 5 + Supervisor Relaunch Flow positive substring pins (agent_started + key + 90 + checklist tokens).
  - setup SKILL mirror pin.
  - Absence-pin against the wrong combined `grep -E 'CLOGLOG_API_KEY|DATABASE_URL' <worktree>/.env` probe (executable-form regex so prose can describe the antipattern).
  - Absence-pin against imperative-retry phrasing.

## Codex round 1 findings (both addressed in 4da538f)

- **[MEDIUM] `.env` API-key probe was inverted.** Original checklist said `grep -E 'CLOGLOG_API_KEY|DATABASE_URL' <worktree>/.env`, but the launcher's `_api_key` resolves env first then `~/.cloglog/credentials`; `.env` is NOT on the resolution path (`tests/test_mcp_json_no_secret.py` and `.cloglog/on-worktree-create.sh` pin the invariant). Following the old checklist literally would have pushed an operator toward a secret-placement violation. Fixed: split into separate probes (`printenv` / `~/.cloglog/credentials` for the key, `.env` for `DATABASE_URL`) and added an executable-form absence-pin so the antipattern can't return.
- **[HIGH] setup SKILL `Handle agent_unregistered` was stale.** It still said "relaunch and proceed" with no `agent_started` wait — re-introducing the silent-hang T-356 was supposed to close. Mirrored the launch SKILL contract verbatim into setup SKILL Step 4 (new). Pin enforces the mirror.

Codex round 2 returned `:pass:` with explicit verification of all five pin cases and the cross-skill mirror.

## Residual TODOs / context the next task should know

- **Post-bootstrap heartbeat** is the obvious next step: a zellij tab killed *after* `agent_started` already fired (operator force-closes the tab mid-task, claude OOMs, etc.) is still invisible to the supervisor. Could be a periodic supervisor sweep over `mcp__cloglog__list_worktrees` looking for stale heartbeat, or a backend-side `last_heartbeat_at` field surfaced on `agent_unregistered`. Explicitly out of scope for T-356; should be filed as a sibling task under F-46 if not already.
- **`gh-app-token.py` resolution from worktrees.** During this task's PR push step, the script failed with `GH_APP_ID is required` because it resolves `.cloglog/local.yaml` relative to `git rev-parse --show-toplevel`, which returns the *worktree* path inside a worktree — and `local.yaml` lived only at the main repo root. The operator unblocked us by exporting env vars; the durable fix is for the script (and/or the launch.sh's `_gh_app_id` / `_gh_app_installation_id` helpers) to walk up to the main repo's `.cloglog/local.yaml` when called from a worktree. Worth filing as a small follow-up — every worktree-agent that needs bot tokens hits this otherwise.
- **AGENT_PROMPT.md inbox-path inconsistency.** The launch SKILL template tells worktree agents to tail `<WORKTREE_PATH>/.cloglog/inbox`, but the AGENT_PROMPT.md generated for this task pointed me at `<project_root>/.cloglog/inbox` (line 84). Webhook PR events fan out to the worktree-local inbox per `src/gateway/webhook_consumers.py`, so the prompt-template path would have made me miss them. I worked around it by spawning a second monitor on the worktree-local path mid-task. Likely the AGENT_PROMPT.md generator (or the prompt-template prose in launch SKILL Step 3) needs to align with the webhook fan-out target — either point agents at both inboxes, or consolidate to one.

## Verification

- `pytest tests/plugins/test_launch_skill_has_agent_started_timeout.py -x` — 5 passed.
- `make quality` — full gate green (1141 tests passed, 88.49% coverage, demo auto-exempt).
- Codex review session 2/5 returned `:pass:`.
- Auto-merge gate: `merge`. PR squashed and merged at 2026-04-30T06:01:57Z.

---
_From wt-t358-narrow-toasts/shutdown-artifacts/work-log-T-358.md:_

---
task: T-358
title: Narrow desktop notifications to operator-attention events
feature: F-46
worktree: wt-t358-narrow-toasts
pr: https://github.com/sachinkundu/cloglog/pull/278
merged_sha: d2cf0a010a04c5dbcdc18a52689350b966e47b1b
codex_sessions: 2
status: merged
---

## What shipped

Two rules in `src/gateway/notification_listener.py`:

1. `TASK_STATUS_CHANGED → review` no longer shells out to `notify-send`. The persisted `Notification` row + `NOTIFICATION_CREATED` SSE for the dashboard bell are unchanged.
2. `EventType.AGENT_UNREGISTERED` toasts only on a known-non-clean `data.reason` (allowlist: `force_unregistered`, `heartbeat_timeout`). A clean unregister via the public API has no `reason` and stays silent — that filter is what keeps a normal post-merge agent exit from toasting.

`AgentService.unregister`, `force_unregister`, and `check_heartbeat_timeouts` publish `AGENT_UNREGISTERED` alongside their existing `WORKTREE_OFFLINE` events. `desktop_toast_enabled: false` in `.cloglog/config.yaml` is the operator off-switch (persisted notifications + SSE unaffected).

## Pin tests

- `tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py` — absence-pin: review-transition fires the row + SSE but does NOT call `asyncio.create_subprocess_exec`. Per CLAUDE.md "Absence-pins on antipattern substrings collide with documentation that names the antipattern", this is mocked at the call surface, not grep'd from source.
- `tests/gateway/test_notification_listener_toasts_on_unregister_filter.py` — five-case filter: clean (None) → silent, `force_unregistered` → toast, `heartbeat_timeout` → toast, unknown reason → silent (allowlist is source of truth), off-switch suppresses non-clean.

## Sessions

- **Codex round 1 (`:warning:`)**: caught two real failure modes — (a) public unregister API has no `reason` parameter so a normal post-merge exit would toast on every merge with the original clean-allowlist filter; (b) `AGENT_BLOCKED` / `CHANGES_REQUESTED_REPEAT` / `AUTO_MERGE_STALLED` / `CLOSE_WAVE_FAILED` had no live producers, so shipping their EventTypes + dispatch branches was dead code. Took the "cut, don't extend" path: removed those event classes, helper classes (`StallDebouncer`, `ChangesRequestedTracker`), tests, and the `desktop_toast_stall_minutes` config. Flipped the unregister filter from clean-allowlist to non-clean-allowlist so `reason=None` (the public-API default) is silent. Commit `035c650`.
- **Codex round 2 (`:pass:`)**: clean approval; auto-merge gate ran and merged.

## Residual TODOs / context the next task should know

- **Other operator-attention event classes are unwired.** The original spec asked for toasts on `agent_blocked`, two-consecutive `CHANGES_REQUESTED`, and auto-merge stalls. Those events live only in inbox files (`<project_root>/.cloglog/inbox`) and worktree-side scripts (`plugins/cloglog/scripts/auto_merge_gate.py`). To revive them, the missing piece is a server-side bridge: either a supervisor seam that mirrors specific inbox lines onto `event_bus`, or a small REST/MCP endpoint agents/scripts call to publish typed events. Once that producer seam exists, the dispatcher branches and `StallDebouncer` / `ChangesRequestedTracker` helpers can come back as a clean follow-up; the design from the first cut is intact in PR #278's first commit (`7b1aa0e`) for reference.
- **`close_wave_failed` is also unwired.** `make quality` failure on the close-wave branch is detected by the close-wave skill itself, not by the gateway. Bridging that to a typed event is the same shape problem.
- **Per-event-class off-switches.** The spec mentioned `toast_on_agent_blocked: true` etc. as a future ergonomic. Not added — current dispatcher is a small `if`/`if`, not a polymorphic table. When the unwired classes come back, refactoring to an event-type → toast-body dict makes per-class flags a one-line extension.
- **No contract change.** `unregister_agent` route + `UnregisterByPathRequest` schema unchanged. If a future task wants the worktree-agent to send `reason="pr_merged"` etc. explicitly (vs the implicit "no reason → clean" today), the schema/contract will need updating.

## Files changed

- `src/gateway/notification_listener.py` — full rewrite (dispatcher + filter + off-switch reader).
- `src/shared/events.py` — added `AGENT_UNREGISTERED` EventType.
- `src/agent/services.py` — `unregister`, `force_unregister`, `check_heartbeat_timeouts` publish AGENT_UNREGISTERED with the same data dict (reason set on non-clean paths only).
- `.cloglog/config.yaml` — added `desktop_toast_enabled: true`.
- `CLAUDE.md` — Notifications section.
- `tests/gateway/test_notification_listener.py` — retired the two stale notify-send tests.
- `tests/gateway/test_notification_listener_does_not_toast_on_review_transition.py` — new.
- `tests/gateway/test_notification_listener_toasts_on_unregister_filter.py` — new.
- `docs/demos/wt-t358-narrow-toasts/{demo.md,demo-script.sh}` — Showboat demo.

---
_From wt-t360-prompt-template/shutdown-artifacts/work-log-T-360.md:_

---
task: T-360
title: AGENT_PROMPT.md → fixed template + per-task task.md — kill workflow drift
pr: https://github.com/sachinkundu/cloglog/pull/279
merged_at: 2026-04-30T07:30:00Z
---
## What shipped

A new canonical workflow template at `plugins/cloglog/templates/AGENT_PROMPT.md`
that the launch SKILL Step 3 copies verbatim into every worktree, plus a
small per-task `task.md` carrying just the delta (UUIDs, paths, title,
description, sibling warnings, residual TODOs hint). Hand-pasting workflow
rules into per-agent prompts is the failure mode this PR closed — the
2026-04-30 incident had three agents tailing the project-root inbox
instead of the worktree inbox because the path was hand-copied.

The launch SKILL's Step 3 was rewritten as: `cp` the template +
quoted-heredoc `task.md` emit + a sed pass for scalars + `mktemp` + sed
`r`/`d` pair for multi-line placeholders. A `_sed_escape_replacement`
helper escapes `&` / `\` / `|` so free-form board strings round-trip
literally.

The continuation flow has ONE task-resolution contract for both initial
launches and continuations: trust `task.md`'s UUID; on backend error,
emit `mcp_tool_error` and halt. The supervisor MUST rewrite `task.md`
before issuing the continuation prompt — that's a hard prerequisite
flagged for T-356's Supervisor Relaunch Flow zone.

## Files touched

- `plugins/cloglog/templates/AGENT_PROMPT.md` (new) — canonical template
- `plugins/cloglog/skills/launch/SKILL.md` — Step 3 rewrite, Continuation
  Prompt + One task per session sections, drop inline prompt
- `plugins/cloglog/agents/worktree-agent.md` — First Steps section
  pointed at task.md; "workflow template" framing
- `plugins/cloglog/skills/setup/SKILL.md` — relaunch flow aligned
- `.gitignore` — un-ignore the shipped template (per-launch copies stay
  ignored via the parent rule)
- `CLAUDE.md` — Workflow drift / templating learning
- `tests/plugins/test_agent_prompt_template_correct_inbox_paths.py` (new)
- `tests/plugins/test_launch_skill_renders_template_and_task_md.py` (new)
- `tests/plugins/test_agent_prompt_template_no_workflow_override_recurrence.py` (new)
- `tests/plugins/test_worktree_agent_md_points_at_task_md.py` (new)
- `tests/plugins/test_plugin_search_guidance.py` — re-targeted at template
- `tests/test_agent_lifecycle_pr_signals.py` — re-targeted at template
- `tests/test_mcp_failure_rule_wording.py` — EXPECTED_LOCATIONS swap
- `docs/demos/wt-t360-prompt-template/exemption.md` — classifier exemption

## Decisions

- **One contract for task resolution.** Initial launches and continuations
  both trust `task.md`'s UUID. The earlier `get_my_tasks` defense was
  removed because (a) `TaskInfo` doesn't expose `task_type`, so the agent
  cannot reproduce the supervisor's pipeline-aware pick, and (b) two
  contracts for the same lifecycle event invite drift.
- **`workflow_override` field dropped.** No persisted source on the board;
  `skip_pr` is exposed only at `update_task_status` time. The agent
  decides at PR time from its own diff (a runtime rule, not a launch-time
  stored field).
- **Multi-line placeholder substitution via sed `r FILE`/`d`** beats inline
  Python. Plugin scripts can't assume PyYAML / Python-stdlib gymnastics;
  whole-line replacement on placeholders that already sit on their own
  line is the simplest correct shape.
- **Sed replacement-string escaping is mandatory** for free-form board
  strings. The `_sed_escape_replacement` helper escapes `&` / `\` / `|`.
- **Continue using a quoted heredoc (`<< 'TASK_EOF'`)** so `${VAR}`
  references in task.md stay literal — same discipline T-353 enforced
  for `launch.sh`.

## Review findings + resolutions

5 codex sessions; PR landed at 5/5 cap with operator review. Findings
addressed in order:

- **Round 1:**
  - MEDIUM — Missing `register_agent` call in template (MCP server stores
    `currentWorktreeId` per-process; supervisor's prior call doesn't
    propagate to spawned session). Resolved: explicit `register_agent`
    call in Standard workflow step 2.
  - MEDIUM — `task.md` staleness on continuation. Resolved (later refined
    in round 5): trust `task.md`, escalate via `mcp_tool_error`,
    supervisor rewrites task.md.

- **Round 2:**
  - MEDIUM — `get_my_tasks`-only resolution can pick wrong task (positions
    aren't pipeline-aware). Resolved: prefer `task.md`'s UUID; fallback
    only on staleness. (Later simplified further in round 4.)
  - HIGH — sed replacement metacharacters not escaped. Resolved:
    `_sed_escape_replacement` helper + adversarial pin test.

- **Round 3:**
  - MEDIUM — Step 3 doesn't substitute multi-line placeholders. Resolved:
    `mktemp` + `printf` + sed `r FILE`/`d`. Renderer test now executes
    Step 3 as-is — any forgotten substitution fails the no-leftover
    assertion.
  - CRITICAL — `worktree-agent.md` still described AGENT_PROMPT.md as the
    "feature assignment and task IDs" file. Resolved: First Steps section
    rewritten to call AGENT_PROMPT.md the workflow template and point at
    task.md for the per-task delta. New pin test prevents reversion.

- **Round 4:**
  - MEDIUM — continuation fallback referenced `task_type` (not on
    `TaskInfo`) and `description` (not on `SearchResult`). Resolved:
    drop the fallback, trust `task.md`, escalate on backend error.
  - HIGH — `workflow_override` had no producer in board / MCP contracts.
    Resolved: drop the field entirely; runtime `skip_pr` decision rule
    in template. Pin test inverted: budget = 0 occurrences of the YAML
    key form.

- **Round 5:**
  - MEDIUM — internal contradiction (Step 3 said don't fall back; the
    Continuation Prompt section said do). Resolved: ONE contract,
    both call sites describe the same flow.
  - HIGH — `worktree-agent.md` still mentioned `optional workflow_override`
    in line 23 (round 4 had only fixed line 23 of a different paragraph).
    Resolved: explicit "No-PR eligibility decided at runtime per
    AGENT_PROMPT.md".

Codex's targeted-test run confirmed `45 passed`. `make quality` clean
post-merge.

## Learnings (candidate for CLAUDE.md)

The Workflow drift / templating learning was added to `CLAUDE.md` as part
of this PR. Other learnings worth capturing in a future fold:

- **MCP per-process registration is per-session, not per-board-row.** A
  worktree row already on the board does NOT mean the spawned MCP
  session can call `mcp__cloglog__*` tools — `currentWorktreeId` and
  `agent_token` live in the spawned process's MCP server state. Every
  agent session must call `register_agent` itself; the backend handles
  it idempotently.
- **`get_my_tasks` orders by `position`, not by pipeline ordering.**
  Out-of-order positions exist on the board and there is no
  pipeline-aware sort in the live API. Agent-side resolvers cannot
  reproduce the supervisor's pick because `TaskInfo` doesn't expose
  `task_type`. Trust the supervisor's `task.md`; escalate on error.
- **Sed replacement-string metacharacters bite free-form board values.**
  Any time you `sed -i "s|@@TOKEN@@|${VAR}|g"`, escape `&` / `\` / the
  chosen delimiter first. `printf '%s' "$VAR" | sed 's/[\\&|]/\\&/g'`
  is the canonical shape.
- **Multi-line placeholder substitution: prefer sed `r FILE`/`d`.** Place
  each multi-line placeholder on its own line; `mktemp` + `printf` +
  whole-line sed substitution beats trying to escape newlines into a
  replacement string.
- **Pin tests on file content can pass while runtime contracts diverge.**
  Codex's round 4 caught two issues that all the new pins missed
  because they were file-shape pins, not contract pins. When a PR adds
  a new field on the agent side, also add a pin that checks the
  producer side (board model / MCP tool schema) actually populates it.
- **One contract per lifecycle event.** When the same event has two
  call-site descriptions (initial launch vs. continuation), keep the
  contract identical; the second description is for *which inputs are
  pre-populated*, not for *what the agent does*. Two contracts invite
  drift.

## Residual TODOs / context the next task should know

- **Supervisor-side `task.md` rewrite** is the proper end state for the
  continuation flow. Until it lands, every continuation hits a 409 on
  the first `start_task` and emits `mcp_tool_error` (correct
  fail-loud-fast). The edit lives in the Supervisor Relaunch Flow
  section of `plugins/cloglog/skills/launch/SKILL.md`, which is T-356's
  zone — file a follow-up task to extend that section to call into the
  same Step 3 rendering shape this PR introduced.
- **Long-form task description / sibling warnings / residual notes are
  populated via env vars in Step 3.** The launching agent (main agent)
  is responsible for setting those env vars before invoking Step 3's
  bash. Until automated wiring lands (a future follow-up), the main
  agent must export `TASK_DESCRIPTION`, `SIBLING_WARNINGS`,
  `RESIDUAL_NOTES` as env vars or rely on the `(none)` defaults.
- **Existing in-flight worktrees keep their hand-built AGENT_PROMPT.md.**
  The new flow only affects new launches. No backfill needed —
  close-wave tears those worktrees down on merge.
- **CLAUDE.md learning was added** but a Workflow drift / templating
  *generalisation* (beyond the inbox-path bug) could be folded in if a
  similar drift class shows up in another plugin surface.
