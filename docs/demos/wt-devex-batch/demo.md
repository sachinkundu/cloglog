# Worktree bootstrap installs the dev toolchain, demo-script templates survive slash-named branches, and devex guidance correctly reflects that mcp-server/dist/ is gitignored.

*2026-04-20T09:22:03Z by Showboat 0.6.1*
<!-- showboat-id: 19002f5c-898b-44cf-8c4f-b102ea53f868 -->

T-250: .cloglog/on-worktree-create.sh now runs 'uv sync --extra dev' + sanity-checks pytest, so fresh worktree venvs ship with the dev toolchain.

```bash
grep -n 'uv sync --extra dev\|pytest not in' .cloglog/on-worktree-create.sh
```

```output
18:  uv sync --extra dev || true
19:  [[ -x "$WORKTREE_PATH/.venv/bin/pytest" ]] || echo "WARN: pytest not in $WORKTREE_PATH/.venv — re-run 'uv sync --extra dev' manually"
```

T-251: demo-script templates in plugins/cloglog/skills/demo/SKILL.md now normalize slash-named branches via ${BRANCH//\//-}, matching scripts/check-demo.sh. Verified: the normalized form is present twice and the raw 'docs/demos/$(git rev-parse ...)' pattern no longer appears.

```bash
printf 'normalized_form_hits=%s\nraw_form_hits=%s\n' "$(grep -cE 'BRANCH//\\/' plugins/cloglog/skills/demo/SKILL.md)" "$(grep -cE 'docs/demos/\$\(git rev-parse' plugins/cloglog/skills/demo/SKILL.md)"
```

```output
normalized_form_hits=2
raw_form_hits=0
```

T-252: no live template carried the 'they are checked in' phrasing — the misstatement existed only in a work-log. CLAUDE.md now documents durably that mcp-server/dist/ is gitignored and auto-rebuilt by on-worktree-create.sh / CI.

```bash
printf 'stale_phrase_in_live_templates=%s\nnew_guidance_in_claude_md=%s\n' "$(grep -l 'they are checked in' plugins/cloglog/skills/*/SKILL.md CLAUDE.md 2>/dev/null | wc -l)" "$(grep -c 'mcp-server/dist.*gitignored' CLAUDE.md)"
```

```output
stale_phrase_in_live_templates=0
new_guidance_in_claude_md=1
```
