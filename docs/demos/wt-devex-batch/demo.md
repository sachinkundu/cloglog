# Worktree bootstrap installs the dev toolchain, demo-script templates survive slash-named branches, and devex guidance correctly reflects that mcp-server/dist/ is gitignored.

*2026-04-20T09:30:14Z by Showboat 0.6.1*
<!-- showboat-id: 18cc4852-fa0b-403f-bc88-dd3771ede746 -->

T-250: .cloglog/on-worktree-create.sh now runs 'uv sync --extra dev' + sanity-checks pytest, so fresh worktree venvs ship with the dev toolchain.

```bash
grep -n 'uv sync --extra dev\|pytest not in' .cloglog/on-worktree-create.sh
```

```output
18:  uv sync --extra dev || true
19:  [[ -x "$WORKTREE_PATH/.venv/bin/pytest" ]] || echo "WARN: pytest not in $WORKTREE_PATH/.venv — re-run 'uv sync --extra dev' manually"
```

T-251: both halves of the demo workflow now normalize slash-named branches via ${BRANCH//\//-}, matching scripts/check-demo.sh. (a) plugins/cloglog/skills/demo/SKILL.md templates produce docs/demos/feat-foo/ paths, (b) scripts/run-demo.sh uses FEATURE_NORM for its directory lookup so 'make demo' actually finds the written path.

```bash
printf 'skill_md_normalized_hits=%s\nskill_md_raw_hits=%s\nrun_demo_uses_feature_norm=%s\n' "$(grep -cE 'BRANCH//\\/' plugins/cloglog/skills/demo/SKILL.md)" "$(grep -cE 'docs/demos/\$\(git rev-parse' plugins/cloglog/skills/demo/SKILL.md)" "$(grep -c 'FEATURE_NORM' scripts/run-demo.sh)"
```

```output
skill_md_normalized_hits=2
skill_md_raw_hits=0
run_demo_uses_feature_norm=2
```

T-252: no live template carried the 'they are checked in' phrasing — the misstatement existed only in a work-log. CLAUDE.md now documents durably that mcp-server/dist/ is gitignored, never committed, and must be rebuilt locally with 'cd mcp-server && make build' when mcp-server/src/ changes (neither on-worktree-create.sh nor CI rebuilds it).

```bash
printf 'stale_phrase_in_live_templates=%s\nnew_guidance_in_claude_md=%s\n' "$(grep -l 'they are checked in' plugins/cloglog/skills/*/SKILL.md CLAUDE.md 2>/dev/null | wc -l)" "$(grep -c 'mcp-server/dist.*gitignored' CLAUDE.md)"
```

```output
stale_phrase_in_live_templates=0
new_guidance_in_claude_md=1
```
