# Wave: reconcile-wt-t435-shell-templating-sweep

**Date:** 2026-05-05
**Worktree:** wt-t435-shell-templating-sweep
**PR:** [#330](https://github.com/sachinkundu/cloglog/pull/330) — `docs(F-58): templating modernization sweep (T-435)`
**Invoked from:** reconcile (close-wave delegation, predicate held)

## Shutdown summary

| Worktree | Shutdown path | Commits | Notes |
|----------|----------------|---------|-------|
| wt-t435-shell-templating-sweep | cooperative (tier 1) | 8 | exit-on-unregister hook regression (T-475); tab closed via helper. Codex round 1 timed out at 355s — the agent pushed an empty-nudge "noop: retry codex review" commit and converged on the next pass |

## Commits

```
6ee4d73 docs(F-58): systematic post-codex grep — add row #31 (init project-create POST)
d1df10c docs(F-58): address codex session 5 — add 2 missed JSON-from-bash sites
c74fec4 docs(F-58): address codex session 4 — separate concrete from protocol-only
12e6faa docs(F-58): address codex session 3 — add need_session_restart to row #14
145c072 docs(F-58): address codex session 2 — fix 3 inaccuracies
741dde5 noop: retry codex review after 355s timeout
2f6872b docs(F-58): address codex review — fix 4 inaccuracies
a9e745b docs(F-58): templating modernization sweep + follow-up tasks
```

## Files changed
- `docs/design/templating-modernization.md` (new — 31-row classification table + phase plan + grep-pattern reference)

## Per-task work log (from `work-log-T-435.md`)

### What shipped
A sweep of every runtime file-synthesis / JSON-from-bash / sed-substitution
site, classified per the T-435 rubric (substitution count, multi-line,
conditionals, special-char risk, currently broken, recommendation, cost,
pin-test, follow-up task). 31 rows.

Phase plan:
- **P1** (done): T-354 / T-437.
- **P2** (fragile): T-466 init config.yaml sed, T-467 demo `exemption.md`.
- **P3** (working-but-fragile): T-462 codex-review-prompt, T-463
  on-worktree-create matrix, T-464 close-wave work-log skeleton, T-465
  per-task work-log.
- **P4** (cleanups): T-468 lifecycle JSON helper + 5 POST bodies, T-469
  pre-commit guard, T-470 worktree-infra .env, T-474 SessionEnd backstop.
- **P5** keep-as-is.

### Follow-up tasks filed under F-58
T-462, T-463, T-464, T-465, T-466 (expedite), T-467 (expedite), T-468,
T-469, T-470, T-474. T-471 deleted as duplicate
(`test_launch_skill_renders_template_and_task_md.py` already covers it).

### Decisions / learnings (operator-led correction)

Codex review across 5 sessions caught 1–4 sites per round — but the
systematic post-codex grep pass (row #31 init project-create POST) found
a site **codex never flagged**. Operator pushed back: relying on
incremental codex prompting was the wrong shape. The doc now includes a
*"How this sweep was conducted (after codex review)"* section enumerating
every grep idiom (`printf '{`, `curl -d "{`, `cat > FILE <<`, `} > FILE`,
`sed -i`, `cat <<EOF | curl`, `tee`, `<<<`, `write_text`) so future
maintainers can reproduce the pass mechanically.

### Recommendation rubric (pinned in doc)
- Multi-line OR special-chars OR conditionals → **Jinja2**
  (`render_template.py` + `uv run --with jinja2`).
- Single-line key=value or trivial → **`string.Template`**.
- Backend Jinja2 is NOT a direct dep — shouldn't become one until
  backend-side rendering needs it. Plugin/hook rendering uses ephemeral
  `uv run --with jinja2`.

### Lifecycle JSON cleanup (T-468) scope expansion
T-468 grew from "one helper for inbox events" through codex's 5
sessions + systematic grep into:
"helper + add three protocol-only event snippets to AGENT_PROMPT.md +
migrate 5 POST bodies + drift test that fails if any
`printf '{"type":` or `curl … -d '"{` survives outside the helper."
The drift test is the structural defense.

## Learnings & Issues

### Routing

- **"Don't trust codex review alone — finish with a systematic grep pass."**
  Codex flagged 24 sites across 5 rounds; the systematic grep found a 25th
  (#31 init project-create POST) codex never caught. The doc itself now
  encodes this lesson (the *How this sweep was conducted* section).
  Generalising it: **whenever an LLM-driven review is the primary
  correctness gate for a sweep, follow it with a deterministic grep against
  the patterns the sweep is meant to find**. Adding to the design doc as the
  routing home; the lesson is sweep/audit-class, not workflow-class.

  No new entry to `docs/invariants.md` — there's no automated pin
  (a "did the agent run the grep?" check would be performative). Captured
  in-document.

- **Codex 355s timeout on a 111-line docs PR is unusual.** Agent worked
  around with `noop: retry codex review` empty nudge. Recurring timeouts
  on small diffs are a tuning signal for `REVIEW_TIMEOUT_*` in
  `src/gateway/review_engine.py`. Single observation today; not yet an
  invariant entry.

### Bug observed (cross-wave): T-475 exit-on-unregister regression
Same survival pattern as wt-t430 and wt-t432. Already filed.

### Quality gate
Passed on main after fast-forward.

## State after this wave

- `docs/design/templating-modernization.md` is the canonical roadmap for
  F-58 (Templating modernization).
- T-462..T-474 (10 tasks) are the prioritized follow-up work; T-466 and
  T-467 marked **expedite** (latent escape footguns).
- Sequencing: T-468 must land before T-464/T-465/T-474 (they share the
  work-log template).
