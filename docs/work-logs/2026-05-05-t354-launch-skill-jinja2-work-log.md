# Work log — wt-t354-launch-skill-jinja2

Closed: 2026-05-05.
Wave name: t354-launch-skill-jinja2 (single-task wave).

## Worktrees

| Worktree | Branch | Tasks | PR | Shutdown path |
|----------|--------|-------|----|---------------|
| wt-t354-launch-skill-jinja2 | wt-t354-launch-skill-jinja2 | T-354 | [#324](https://github.com/sachinkundu/cloglog/pull/324) | cooperative — `agent_unregistered` 2026-05-05T09:14:32+03:00 (`reason=pr_merged`); launcher then survived (T-428 recurrence — third time this session), tab close cleared it |

## What shipped (from `work-log-T-354.md`)

Replaced the launch SKILL's heredoc + sed templating pipeline with a deterministic Python renderer:

- **`plugins/cloglog/templates/launch.sh.template`** — tracked static bash template with `@@WORKTREE_PATH@@` / `@@PROJECT_ROOT@@` placeholders. Was previously encoded as quoted-heredoc lines inside `SKILL.md`.
- **`plugins/cloglog/templates/task.md.template`** — tracked static Markdown template with the per-task delta placeholders (`@@TASK_NUMBER@@`, `@@TASK_TITLE@@`, …, `@@RESIDUAL_NOTES@@`).
- **`plugins/cloglog/scripts/render_template.py`** — stdlib-only renderer using `str.replace`. Values via `--var KEY=VALUE` flags or env. Strict by default; `--allow-unset` opts in to empty-string fallback.
- **`plugins/cloglog/skills/launch/SKILL.md`** — recipe shape: `cp` the workflow template, then invoke `render_template.py` with `--var` bindings. No bash escape gymnastics anywhere.
- **`plugins/cloglog/docs/launch-design.md`** — moved T-353 / T-354 / T-360 / T-378 / T-382 / T-384 / T-387 rationale here so the SKILL prose stays short.
- `.gitignore` — un-ignored `templates/task.md.template`; ignored per-worktree `task.md`.

PR #324 merged 2026-05-05T06:13:17Z. Codex `:pass:` first session. CI green.

### Decision: stdlib `string.Template`-class substitution, not Jinja2

The renderer uses literal `str.replace` against `@@KEY@@` placeholders rather than introducing Jinja2 as a new dependency. Discussion in this session led with Jinja2 as the strawman; the agent landed on stdlib because:

- The template surface is two files with flat scalar substitutions and no conditionals/loops.
- Avoiding the new dependency keeps init-smoke portability ([init on a fresh repo with only stdlib python] tested in `test_init_on_fresh_repo.py`) trivially green.
- The `@@KEY@@` sigil is already in use across the plugin and remains unambiguous against bash, sed, regex, and markdown.

This decision needs to be revisited if (and only if) future templating sites require conditionals, loops, or includes — F-58/T-435 sweep is the natural place to make that call. The choice is documented in `plugins/cloglog/docs/launch-design.md`.

### Pin tests

- `test_launch_skill_renders_clean_launch_sh` — adversarial paths `~/fake&wt|odd\dir/foo`, asserts `bash -n`, `$1`/`$2` survive, fallback prompt absolute, no `@@KEY@@` leaks. **Direct regression for the bug class.**
- `test_launch_skill_renders_template_and_task_md` — verifies AGENT_PROMPT.md verbatim copy + task.md rendering, including adversarial titles, multi-line descriptions, residuals.
- Six existing pin tests redirected to read `launch.sh.template` directly.
- Absence pin: SKILL.md no longer contains `cat > .../launch.sh` or `_sed_escape_replacement`.

## Shutdown summary

- Cooperative path: `agent_unregistered` cleanly with `reason=pr_merged` and per-task work log path delivered.
- **Launcher survived `unregister_agent`** — same T-428 recurrence pattern. PID 2076415 + claude underneath were still alive when close-wave Step 6 ran `pgrep`. Tab close (via `close-zellij-tab.sh`) terminated claude via SIGHUP; launcher's `wait` returned and process exited naturally without trap fire — `/tmp/agent-shutdown-debug.log` had no entry. **Third confirmed recurrence in this supervisor session.**
- The pattern is now: every cleanly-merging session in this supervisor exhibits the same hook-failure shape. T-428 should be expedited.

## Learnings & invariants routed

The agent self-routed rationale into `plugins/cloglog/docs/launch-design.md` (heredoc/sed history, T-353/T-360/T-378/T-382/T-384/T-387 context). No `docs/invariants.md` change needed — the templating-class invariant is now expressed by the existing pin tests.

### Residual TODOs surfaced (file as follow-ups)

- **`gh pr merge --squash --delete-branch` worktree-collision when run from inside a worktree.** Symptom: `failed to run git: fatal: 'main' is already used by worktree at '/home/sachin/code/cloglog'`. The merge succeeded server-side; only the local-side branch-delete cleanup crashed. Filed as a github-bot SKILL follow-up.
- **`gh-app-token.py` doesn't read `local.yaml` from worktrees.** The launch-time export of `GH_APP_ID` / `GH_APP_INSTALLATION_ID` was lost across `/clear` (or never landed in this session). Worktree's `.cloglog/` has only `config.yaml`, masking the project-root `local.yaml`. Worth a follow-up under T-348's lineage.
- **Plugin's own `docs/` and `scripts/` not in demo classifier allowlist.** Future plugin-internal changes will keep tripping the classifier. Consider widening `^plugins/[^/]+/(hooks|skills|agents|templates)/` to also include `docs|scripts`.
- **No `task.md` regression test for the gitignore.** The new ignore line covers `task.md` at any depth and un-ignores `templates/task.md.template`. Worth a small `git check-ignore` pin alongside `test_agent_prompt_template_correct_inbox_paths`.

## State after this wave

- **Launch SKILL refactor SHIPPED.** Heredoc + sed templating pipeline removed; deterministic stdlib renderer with adversarial-path pin tests in place. The systematic `Read /AGENT_PROMPT.md and begin.` bug is gone — every future supervisor launch should produce a launch.sh whose fallback prompt resolves to the absolute worktree path verbatim.
- T-428 (exit-on-unregister hook) recurrence count: 3 in this session (wt-t394, wt-t30 antisocial, wt-t354). Pattern is deterministic, not flaky. Should be expedited.
- F-57 (backend close-off) and T-435 (templating sweep) remain next-up under E-10.
