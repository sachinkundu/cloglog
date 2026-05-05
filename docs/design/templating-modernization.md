# Templating modernization — sweep & action plan

**Status:** Design doc / sweep output. Filed under F-58 (Templating modernization). Source task: T-435.

This document enumerates every site in the repo that synthesises a file at runtime from a string-with-placeholders, classifies each, and recommends a migration target. It is read-only on the target sites — no migration code lands here. Each concrete migration is filed as its own follow-up task under F-58.

## Background — what's already done

- **T-354** — `plugins/cloglog/skills/launch/SKILL.md` was the canonical heredoc-+`sed` site. T-354 extracted the static template to `plugins/cloglog/templates/launch.sh.template` and added `plugins/cloglog/scripts/render_template.py` as the deterministic renderer. The post-`sed` substitution was retired. T-360 split per-task delta into `task.md` rendered from `task.md.template` via the same engine.
- **T-437** — replaced render_template.py's literal-replace engine with Jinja2 (autoescape OFF, `StrictUndefined`). Placeholder syntax `{{ key }}`. Special characters (`&`, `\`, `|`, newlines) round-trip verbatim — that closed the `_sed_escape_replacement` bug class for the launch site.

The template engine that downstream migrations should reuse:

```
uv run --with jinja2 "${CLAUDE_PLUGIN_ROOT}/scripts/render_template.py" \
  --template <abs/path/to/template> \
  --output  <abs/path/to/output> \
  --var key=value [--var ...]
```

The runner uses `uv run --with jinja2` — Jinja2 is **not** a direct backend dependency (`pyproject.toml`/`uv.lock` carry no `jinja2` line). It is provisioned ephemerally per invocation, so any host with `uv` can render without touching the project venv. Hooks and scripts that cannot assume `uv` is available should prefer `string.Template` from stdlib.

## Sweep — every templating site

Sites are walked in source order: `templates/`, `scripts/`, `skills/`, `hooks/`, `src/`. "Currently broken?" is **no** unless an open bug is linked.

| # | Site | Subs | Multi-line? | Cond/loops? | Special chars? | Broken? | Recommendation | Cost | Pin test | Follow-up |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `plugins/cloglog/templates/launch.sh.template` rendered via `render_template.py` (called from `skills/launch/SKILL.md:231-235`) | 2 (`worktree_path`, `project_root`) | no | no | yes (paths) | no | **DONE — keep** (Jinja2 already, T-354+T-437) | — | exists (T-437) | — |
| 2 | `plugins/cloglog/templates/task.md.template` rendered via `render_template.py` (called from `skills/launch/SKILL.md`, T-360) | 9 | yes (`task_description`, `sibling_warnings`, `residual_notes`) | no | yes | no | **DONE — keep** (Jinja2 already) | — | T-437 covers engine; site-specific snapshot would be nice | T-471 (snapshot) |
| 3 | `plugins/cloglog/templates/AGENT_PROMPT.md` — copied verbatim (no substitution) | 0 | n/a | n/a | n/a | no | **keep-as-is** — verbatim copy is the correct shape; the launch SKILL hand-rolls per-task delta into sibling `task.md` to keep this file static across launches. | — | byte-equality test exists per `docs/launch-design.md:99` | — |
| 4 | `plugins/cloglog/templates/claude-md-fragment.md` — appended verbatim by init Step 5 | 0 | n/a | n/a | n/a | no | **keep-as-is** | — | n/a | — |
| 5 | `plugins/cloglog/templates/review-guidelines-fragment.md` — appended verbatim by init Step 7b | 0 | n/a | n/a | n/a | no | **keep-as-is** | — | n/a | — |
| 6 | `plugins/cloglog/templates/codex-review-prompt.md` — read by init Step 7a, then the agent generates a project-specific `.github/codex/prompts/review.md` by **adding** tech-stack-specific bullets | varies (per stack) | yes (multi-bullet adds) | yes (per-stack conditionals) | no | no | **extract-static-template+jinja2** — convert to Jinja2 with `{% if stack.python %}`/`{% if stack.frontend %}`/etc. blocks; init reads detected stacks and renders deterministically rather than asking the agent to splice freehand. Today's "agent generates" shape is lossy across operators and undermines the init-smoke contract. | M | snapshot per stack (Python, TS, React, Rust, mixed) | T-462 |
| 7 | `plugins/cloglog/templates/codex-review-schema.json` — copied verbatim by init Step 7a | 0 | n/a | n/a | n/a | no | **keep-as-is** | — | n/a | — |
| 8 | `plugins/cloglog/skills/init/SKILL.md:310-329` — three `sed -i "s/^KEY:.*/KEY: ${VAR}/"` updates against `.cloglog/config.yaml` (`project`, `project_id`, `backend_url`) | 3 | no | yes (per-key if-exists branch) | yes — `BACKEND_URL` contains `://` so the third uses `\|` separator already; future values may break | **YES (latent)** — slug or URL with delimiter chars trips the `sed` substitutor | **jinja2** via a small Python helper — load YAML, set keys, dump back. Avoids both the `sed` escaping risk and the duplicate-key footgun the comment at line 317 already calls out. | S | snapshot: input config.yaml + values → expected output; regression: value containing `&`, `|`, `/`, `\` | T-466 |
| 9 | `plugins/cloglog/docs/setup-credentials.md:139-149` — same three `sed -i` updates documented for operators | 3 | no | yes | yes | same as #8 | follow #8 — replace example with helper invocation once #8 ships | XS | n/a (docs only) | folded into T-466 |
| 10 | `plugins/cloglog/skills/init/SKILL.md:601-612` — `cat >> .cloglog/config.yaml <<'YAML' ... YAML` appending the commented `worktree_scopes:` stub | 0 | yes | no | no | no | **keep-as-is** — quoted heredoc, no substitution. The block is a static instructive comment for the operator. Migration would be churn. | — | n/a | — |
| 11 | `plugins/cloglog/skills/init/SKILL.md:623-660` — Step 4b generates `on-worktree-create.sh` per detected stack (Python+uv, Python+pip, Node, Rust, Go) | per-stack | yes | yes (per-stack branching done by the agent today) | no | no | **extract-static-template+jinja2** — move each per-stack block to `plugins/cloglog/templates/on-worktree-create.<stack>.sh` (no substitution needed once split — `WORKTREE_PATH` is bash env, not template var). Init Step 4b becomes `cp` of the matching file. Agents should not be hand-rendering bash. | S | per-stack snapshot test: detect → file path → byte equality | T-463 |
| 12 | `plugins/cloglog/skills/demo/SKILL.md:124-145` — `cat > "$DEMO_DIR/exemption.md" <<MD ... MD` (unquoted, with `$DEMO_DIR` and `$(date -u ...)` and pasted classifier reasoning + file list) | 4 | yes (classifier reasoning paragraph; multi-line file list) | no | yes — classifier reasoning is free-form prose with backticks, paths can contain `&` | no (unquoted heredoc still works, but free-form prose with `\`` will trip the shell) | **jinja2** via `render_template.py` — stable shape, `diff_hash`/`reasoning`/`file_list` come from the classifier output. The `scripts/check-demo.sh` reader pins frontmatter shape; a snapshot test enforces it. | XS | snapshot: fixed reasoning + diff_hash + file list → expected exemption.md; special-chars regression for reasoning containing backticks and pipe | T-467 |
| 13 | `plugins/cloglog/skills/github-bot/SKILL.md:67-110` — `gh pr create --title ... --body "$(cat <<'EOF' ... EOF)"` | 0 (quoted heredoc; the `<…>` placeholders are AGENT-filled prose, not shell substitutions) | yes | n/a | n/a | no | **keep-as-is** — the body is a *prompt for the agent to fill in*, not a runtime renderer. Mirrors `.github/pull_request_template.md`. Migrating would replace agent reasoning with a renderer that has no inputs. | — | `tests/plugins/test_pr_template_mirrors_pull_request_template.py` already pins shape (verify on follow-up) | — |
| 14 | `plugins/cloglog/skills/github-bot/SKILL.md:191` and `templates/AGENT_PROMPT.md:181-185` — `printf '{"type":"pr_merged_notification",...}\n' "$(date -Is)"` writing inbox JSON events | 5–7 | no | no | yes — values may contain shell-special chars in branch/wt names | no | **string.Template** in a tiny helper (`scripts/inbox-event.py emit pr_merged_notification --task=T-NNN ...`) — JSON via `json.dumps` removes any escape risk. Jinja2 is overkill for one-line JSON. | S | snapshot test per event type; round-trip parse | T-468 |
| 15 | `plugins/cloglog/skills/github-bot/SKILL.md:62` — `git push "https://x-access-token:${BOT_TOKEN}@github.com/${REPO}.git"` | 2 | no | no | no | no | **keep-as-is** — bash variable expansion in a one-shot command; not a file-rendering site. | — | n/a | — |
| 16 | `plugins/cloglog/skills/close-wave/SKILL.md` Step 4 — work-log skeleton (described in prose only; no template file or heredoc — agent generates Markdown freehand) | many | yes | yes (loop per worktree + per task) | no | no | **extract-static-template+jinja2** — move skeleton to `plugins/cloglog/templates/work-log.md.template` with Jinja2 loops over `{worktrees: [{commits, files, pr_number, title, tasks: [...]}]}`. Today's freehand generation is the largest variability source between waves. | M | snapshot: fixture wave context → expected work-log.md | T-464 |
| 17 | `plugins/cloglog/agents/worktree-agent.md` Per-Task Work-Log Schema (described in prose only; agent writes `shutdown-artifacts/work-log-T-<NNN>.md` freehand each shutdown) | many | yes | no (per-task instance) | no | no | **extract-static-template+jinja2** — `templates/work-log-T-NNN.md.template` with frontmatter + sections; `AGENT_PROMPT.md` Step 4 of shutdown becomes "render with these vars". Freehand emission is why close-wave Step 5d sees inconsistent log shapes. | S | snapshot: fixture task context → expected per-task log | T-465 |
| 18 | `plugins/cloglog/skills/close-wave/SKILL.md:425-428` — commit message body for the wave-fold commit (`chore(close-wave): <wave-name>\n\nCo-Authored-By: ...`) | 1 | yes | no | no | no | **keep-as-is** — single substitution, single use, no escape risk. | — | n/a | — |
| 19 | `plugins/cloglog/scripts/install-dev-hooks.sh:28-49` (and the duplicate at `scripts/install-dev-hooks.sh:28-49`) — `cat > "${HOOK_PATH}" <<'HOOK' ... HOOK` writing the pre-commit guard | 0 | yes | no | no | no | **extract-static-template** — move hook body to `plugins/cloglog/templates/pre-commit-main-guard.sh`, install via `cp` + `chmod +x`. No Jinja2 needed (zero subs). The duplicate file is a separate dedupe task — cited but out of scope here. | XS | snapshot: rendered file byte-equal to template | T-469 |
| 20 | `scripts/worktree-infra.sh:55-61` — `cat > "$WORKTREE_PATH/.env" <<EOF ... EOF` (5 vars) | 5 | no | no | no — values are port numbers and DB names | no | **string.Template** — single-line key=value pairs, stdlib enough. Jinja2 is overkill but acceptable if uv is mandated. | XS | snapshot: fixed env → expected .env content | T-470 |
| 21 | `plugins/cloglog/hooks/require-task-for-pr.sh` and `enforce-inbox-monitor-after-pr.sh` — five `cat >&2 << MSG ... MSG` diagnostic stderr blocks per file | varies (mostly 1–3 path/URL subs in unquoted variants) | yes | no | yes (BACKEND_URL) | no | **keep-as-is** — these are pure error messages to stderr, not file rendering. Free-form prose at the boundary; a renderer would harm legibility. | — | n/a | — |
| 22 | `plugins/cloglog/docs/setup-credentials.md:364` — `cat <<'MODELFILE' \| ollama create ...` | 0 | yes | no | no | no | **keep-as-is** — operator-facing copy-paste recipe in docs. | — | n/a | — |
| 23 | `src/board/templates.py` — `close_worktree_template()` builds title + description via Python string concat | 1 | yes | no | no | no | **keep-as-is** — single Python constant with one `f"…"` substitution. Comment in the file already says "promote when there's a second one". Don't pre-design. | — | existing close-wave Step 4 + auto-close-off task tests | — |
| 24 | `src/**` (backend) general Jinja2 / templating | n/a | n/a | n/a | n/a | n/a | **none today** — backend has no HTML/email rendering yet. The only `Template` reference is `src/board/templates.py` (#23). Adding Jinja2 as a direct dep is **not** justified by current usage; render_template.py's `uv run --with jinja2` shape is correct for the plugin. | — | — | — |

## Out-of-scope sites considered and ruled out

These were enumerated and *deliberately not* migrated:

- **PR body templates** (#13) — agent-fill prompt, not runtime renderer.
- **Hook diagnostic stderr blocks** (#21) — boundary error messages; legibility > consistency.
- **Bash variable expansions in one-shot commands** (#15) — not file rendering.
- **`docs/setup-credentials.md` operator recipes** (#22) — copy-paste docs.
- **`src/board/templates.py`** (#23) — one constant; the file's own comment defers promotion.

## Action plan

### Phase 1 — urgent (already done)
- ✅ T-354: launch SKILL canonical migration. Sets the pattern.
- ✅ T-437: render_template.py engine swap to Jinja2 + StrictUndefined.

### Phase 2 — broken or fragile sites
- **T-466** (`init` config.yaml `sed -i` updates) — latent escape footgun on slug/URL chars. Highest priority of the remaining sites. (priority: expedite)
- **T-467** (`demo` exemption.md) — unquoted heredoc with classifier-supplied prose; ships a `\`` away from corruption. (priority: expedite)

### Phase 3 — working-but-fragile (multi-line, conditionals, freehand agent emission)
- **T-462** (`codex-review-prompt.md` per-stack additions) — agent-driven generation is lossy.
- **T-463** (`on-worktree-create.<stack>.sh` extraction) — agents shouldn't hand-render bash.
- **T-464** (close-wave work-log skeleton) — largest variance between waves.
- **T-465** (per-task `work-log-T-NNN.md` schema) — drives close-wave Step 5d consistency.

### Phase 4 — low-value cleanups
- **T-468** (inbox JSON event helper) — escape safety, but printf works today.
- **T-469** (pre-commit guard hook extraction) — zero subs; pure cleanup.
- **T-470** (worktree-infra `.env`) — XS, no current bug.
- **T-471** (`task.md.template` snapshot test) — engine is pinned by T-437; site-specific belt-and-suspenders.

### Phase 5 — keep-as-is
Documented in the table above. The decision is to not migrate these and to fold the rationale into reviewer guidance so future sweeps don't re-litigate them.

## Pin-test pattern (applies to every Phase-2/3/4 task)

Each migration follows the same shape:

1. Snapshot test: fixture inputs → expected rendered output, byte-equal.
2. Special-chars regression: at least one fixture variant whose values contain `&`, `|`, `\`, spaces, and a newline (where the field accepts multi-line). This is the direct repeat-defense for the `_sed_escape_replacement` bug class T-354 closed.
3. Where applicable: round-trip parse (e.g. JSON event re-parsed; YAML config re-loaded) to assert structural equivalence beyond byte-equality.

The tests live alongside the migrated site (`tests/plugins/...` for plugin sites, `tests/scripts/...` for repo scripts) and run under `make quality`.

## Dependency note

Jinja2 stays out of `pyproject.toml`. Plugin renderers use `uv run --with jinja2 render_template.py`. Sites that cannot assume `uv` (e.g. a hook firing in a context that hasn't bootstrapped uv yet) use `string.Template` from stdlib — explicit recommendations on the table above mark which.

If a future migration genuinely needs Jinja2 in-process from the FastAPI backend (e.g. HTML email), that migration adds the direct dep in the same PR and updates this section.
