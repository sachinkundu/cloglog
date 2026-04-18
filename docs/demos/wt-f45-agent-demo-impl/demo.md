# Agents now have a structured proof-of-work demo skill that enforces demo documents in every PR, with make quality blocking commits when demos are missing.

*2026-04-18T15:08:31Z by Showboat 0.6.1*
<!-- showboat-id: 3550dc61-7ec7-4655-99a7-e5e6a7365ad8 -->

Task 0: run-demo.sh now falls back to full branch name for worktree branches

```/tmp/show-task0.sh

```

```output
      # Fall back to the full branch name — check-demo.sh already uses this convention
      FEATURE="$BRANCH"
      ;;
  esac
fi
```

Task 1: demo skill created at plugins/cloglog/skills/demo/SKILL.md

```/tmp/show-task1.sh

```

```output
---
name: demo
description: Proof-of-work demo with Showboat and Rodney — invoked before every PR
user-invocable: false
---
```

Task 2: make quality now includes demo-check as the last step before PASSED

```/tmp/show-task2.sh

```

```output
	@echo "  Demo:"
	@$(MAKE) --no-print-directory demo-check && echo "    verified           ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
	@echo "── Quality gate: PASSED ────────────────"
```

Task 3: worktree-agent.md has explicit demo skill invocation checkpoint before PR

```/tmp/show-task3.sh

```

```output
3. Before creating a PR — invoke the demo skill
   Invoke `Skill({skill: "cloglog:demo"})` to produce the proof-of-work demo.
   This is a named checkpoint, not optional. The skill walks you through the
```

Task 5: demo-reviewer subagent definition at .claude/agents/demo-reviewer.md

```/tmp/show-task5.sh

```

```output
---
name: demo-reviewer
description: Reviews proof-of-work demo documents — runs showboat verify, checks stakeholder framing, validates demo substance
tools:
  - Read
```

Task 6: github-bot PR template now has ## Demo / ## Tests / ## Changes ordering

```/tmp/show-task6.sh

```

```output
GH_TOKEN="$BOT_TOKEN" gh pr create --title "feat: ..." --body "$(cat <<'EOF'
## Demo

<One-sentence feature description from the stakeholder's view>

Demo document: [`docs/demos/<branch>/demo.md`](docs/demos/<branch>/demo.md)
Re-verify: `uvx showboat verify docs/demos/<branch>/demo.md`

## Tests

...

```

demo-check is wired into make quality as the last enforcement step

```/tmp/show-democheck.sh

```

```output
	@echo "  Demo:"
	@$(MAKE) --no-print-directory demo-check && echo "    verified           ✓" || (echo "    FAILED ✗" && exit 1)
	@echo ""
```
