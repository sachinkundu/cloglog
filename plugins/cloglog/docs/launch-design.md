# Launch SKILL — Design Notes

This file collects the rationale and history for the launch SKILL. The
SKILL itself (`plugins/cloglog/skills/launch/SKILL.md`) is intentionally
kept short — a recipe that delegates the mechanical work to scripts.
Long-form context lives here so future readers can ground a change without
having to spelunk through git blame.

## Components

```
plugins/cloglog/
├── skills/launch/SKILL.md             # Recipe — step-by-step, no business logic
├── templates/
│   ├── AGENT_PROMPT.md                # Workflow rules — copied verbatim
│   ├── task.md.template               # Per-task delta — rendered
│   └── launch.sh.template             # Bash launcher — rendered
└── scripts/
    └── render_template.py             # Deterministic @@KEY@@ → value
```

## Rendering contract

`render_template.py` substitutes `@@KEY@@` placeholders (where `KEY`
matches `[A-Z_][A-Z0-9_]*`) with values supplied via `--var KEY=VALUE`
or the process environment. Replacement is a literal Python
`str.replace`, so values containing shell or sed metacharacters
(`&`, `\`, `|`, `$`, newlines, etc.) round-trip verbatim.

Strict by default: any unset `@@KEY@@` token after the substitution
pass fails the script with exit 1. `--allow-unset` opts in to empty-
string fallback.

## History

### T-353 — quoted-heredoc discipline for `launch.sh`

The original SKILL emitted `launch.sh` from an *unquoted* heredoc with
`\$1` / `\$2` escapes for helper-function positional args. When the
SKILL block was relayed across the LLM-agent Bash-tool → bash boundary,
those escapes collapsed inconsistently, producing rendered files like
`local file="\"; local key="\"` and tripping
`unexpected EOF while looking for matching '"'` at exec time.

T-353 switched to a *quoted* heredoc (`<< 'EOF'`) so bash performed zero
expansion inside it. Operator-host-specific values (`WORKTREE_PATH`,
`PROJECT_ROOT`) were baked in afterwards via `sed -i` against
`@@WORKTREE_PATH@@` / `@@PROJECT_ROOT@@` placeholders. That bought us
correctness on the bash boundary, but introduced the next bug class.

### T-354 — drop heredoc + sed entirely

With T-353's `sed -i` substitution in place, host paths containing sed
replacement metacharacters (`&` expanded to the matched pattern, `\`
escaped, the chosen `|` delimiter ended the replacement) silently
corrupted the rendered file. The mitigation was a `_sed_escape_replacement`
helper that prefixed `\\` to each metacharacter — but the helper used a
positional arg (`$1`), and **that** reference was lost on the round-trip
from SKILL.md → supervisor's prompt → bash. The escape returned empty
for every value, so every `sed -i` substitution became a no-op against
the placeholder. The visible failure was every supervisor-rendered
`launch.sh` shipping with a fallback prompt of literal
`Read /AGENT_PROMPT.md and begin.` (the `${WORKTREE_PATH}` placeholder
text was substituted with empty string).

The fix is to stop trying to escape one shell language inside another
inside a third. `render_template.py` does literal Python `str.replace`
— there is no shell or sed metacharacter that has special meaning in
the replacement value. The same script handles `task.md` rendering
(replacing the prior heredoc + multi-pass sed with `r FILE` for
multi-line values).

The bash-side SKILL recipe shrinks to a single `python3 render_template.py`
invocation per file, with `--var KEY=VALUE` flags carrying the bindings.
This is also why both files are now tracked under `templates/`: a
template living in version control can be linted, syntax-checked, and
diffed across history; a template encoded as bash heredoc lines inside a
Markdown SKILL.md cannot.

### T-360 — workflow rules in one template, not pasted per-agent

Pre-T-360, each launch's `AGENT_PROMPT.md` was assembled by hand-pasting
inbox paths, MCP preload, etc. into a per-agent prompt. Three agents
shipped with the wrong inbox file (project-root vs. worktree) on
2026-04-30 and sat idle for 25 minutes after operator retries went to
the wrong file. T-360 fixed it by carving the workflow rules out into
`templates/AGENT_PROMPT.md` and copying it verbatim. The launch SKILL no
longer paraphrases the template.

The pin
`tests/plugins/test_launch_skill_renders_template_and_task_md.py::test_step3_emits_both_files_with_substituted_placeholders`
asserts byte-for-byte equality between the rendered `AGENT_PROMPT.md`
and the source template — any future paraphrasing breaks CI.

### T-378 — register before `on-worktree-create.sh`

Step 4b (`mcp__cloglog__register_agent`) must run before Step 4c
(`.cloglog/on-worktree-create.sh`). The project-specific bootstrap
posts to `/api/v1/agents/close-off-task`, which requires the worktree
to be registered first. The 2026-04-24 incident: the script ran before
register, the backend returned 404 "Worktree not registered", and the
script warn-and-continued — every cleanly-completed worktree on the
host then lacked a close-off task and reconcile's close-wave delegation
predicate silently failed. Pinned by
`tests/plugins/test_launch_skill_register_before_on_worktree_create.py`.

### T-382 / T-398 — per-project credentials

`launch.sh.template`'s `_api_key` resolves the project API key in this
order:

1. `CLOGLOG_API_KEY` env (operator override)
2. `~/.cloglog/credentials.d/<project_slug>` (per-project)
3. `~/.cloglog/credentials` (legacy global, only when `project_id` is
   not set in `config.yaml`)

The slug comes from `<project_root>/.cloglog/config.yaml: project` with
a `basename($PROJECT_ROOT)` fallback. Once `credentials.d/<slug>` exists
*at all* it must yield a usable key — present-but-unreadable /
present-but-empty / present-as-directory short-circuits to `return 0`
and the trap-fired `_unregister_fallback` skips the POST instead of
authenticating as the wrong project. Mirrors `mcp-server/src/credentials.ts`
`loadApiKey` byte-for-byte; pinned by
`tests/plugins/test_launch_skill_per_project_credentials.py`.

### T-384 — single zellij JSON contract

Every zellij call site in the plugin (close-zellij-tab.sh helper,
supervisor relaunch flow, launch SKILL Step 4e, and the Step 5
diagnostic checklist) reads from `zellij action list-tabs --json | jq`.
The `.active` boolean on each tab payload identifies the focused tab.

Step 4e captures the current tab's stable numeric ID *before* spawning
the new tab, then chains `new-tab + go-to-tab-by-id` in one shell call
so the visible focus swap is single-frame. Issuing them as separate
Bash calls leaves a brief window where the supervisor's prompt is
hidden.

### T-387 — live plugin loading

`launch.sh.template` invokes `claude --plugin-dir
$WORKTREE_PATH/plugins/cloglog` so plugin edits in the worktree take
effect on the next agent launch. Without the flag, claude resolves the
cloglog plugin from its install-time cache (`claude plugins install`),
freezing the plugin contents at install time and silently invisible to
any agent launched after the edit. Pinned by
`tests/plugins/test_launch_sh_loads_plugin_live.py`.

### T-348 — GitHub App env across `/clear`

`/clear` re-execs the agent in the same zellij tab, re-invoking `bash`.
Whether the operator's RC-file env (`GH_APP_ID`,
`GH_APP_INSTALLATION_ID`) survives that re-invocation is host-specific.
The fix is two-pronged: (a) `gh-app-token.py` resolves them itself from
env → `.cloglog/local.yaml` → `.cloglog/config.yaml`, so non-worktree
callers (close-wave, reconcile, init Step 6c) work without env priming;
(b) `launch.sh.template` exports them into the worktree-agent shell so
downstream `gh` calls that read the env directly keep working across
`/clear`. Pinned by
`tests/plugins/test_launch_skill_exports_gh_app_env.py`.

### T-332 — per-task model selection

`launch.sh.template` reads `${WORKTREE_PATH}/.cloglog/task-model` at
runtime and passes the value to `claude --model`. The supervisor
rewrites the file before each continuation relaunch so the correct
model is used for every task, not just the initial one. The
`${_MODEL_FLAG:+$_MODEL_FLAG}` shape makes a missing model a no-op
(default model) rather than a crash. Pinned by
`tests/plugins/test_launch_skill_model_selection.py`.

## Editing rules

- **Never edit the rendered `launch.sh` or `task.md` in-place.** Edit the
  template under `templates/` and re-launch. A hand-edit on the
  rendered file is overwritten on the next launch and looks like a
  silent regression.
- **Adding a new placeholder?** Add it to the template, add a
  corresponding `--var KEY=VALUE` line in SKILL.md, and add a pin test
  that asserts the binding round-trips for an adversarial value (one
  that contains `&`, `|`, `\` or a newline).
- **Adding a new template?** Place it under `plugins/cloglog/templates/`,
  follow the same `@@KEY@@` placeholder convention, and call
  `render_template.py` from the SKILL with explicit `--var` bindings.
  Do not add a second rendering pathway — there is one contract.
