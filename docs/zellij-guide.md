# Zellij Tab Management — Rules for Agents

## Creating Tabs

Always create tabs with a name:
```bash
zellij action new-tab --name "wt-search"
```

Tab names must match the worktree name they serve. Never use generic names like "test-launch" or "agents".

## Closing Tabs

**ONLY close tabs YOU created.** Never close tabs you didn't create. Never close tabs by index or position.

To close a tab by name:
```bash
# Step 1: Get the TAB_ID from list-tabs
TAB_ID=$(zellij action list-tabs 2>/dev/null | awk -v name="wt-search" '$3 == name {print $1}')

# Step 2: Close by TAB_ID (NOT position)
if [[ -n "$TAB_ID" ]]; then
  zellij action close-tab --tab-id "$TAB_ID"
fi
```

**Critical:** `list-tabs` returns three columns: `TAB_ID POSITION NAME`. Use `TAB_ID` (column 1) with `--tab-id`, NOT `POSITION` (column 2). They are different numbers.

**Never:**
- Close a tab by guessed index
- Close a tab whose name you don't recognize
- Close a tab without verifying the name matches what you expect
- Use `query-tab-names` for closing — use `list-tabs` which gives proper TAB_IDs

## Launching Agents in Tabs

```bash
# Create named tab
zellij action new-tab --name "wt-search"
sleep 1

# Write command and execute
zellij action write-chars "cd /path/to/worktree && claude --dangerously-skip-permissions 'Read AGENT_PROMPT.md and begin.'"
sleep 0.5
zellij action write 13   # Enter to execute shell command

# Return to your tab
sleep 2
zellij action go-to-tab 1
```

The positional prompt argument (`'prompt here'` after `--dangerously-skip-permissions`) auto-submits. No manual Enter needed for the Claude prompt.

## What Does NOT Work

- `zellij action write 10` or `write 13` to submit a prompt inside Claude REPL — doesn't work
- `-p` flag — prints and exits, not interactive
- `--agent` flag — doesn't reliably auto-start
- Launching claude first, then trying to paste and submit a prompt — requires manual Enter

## Relaunching a Crashed Agent

Use `--continue` to resume the previous session:
```bash
cd /path/to/worktree && claude --dangerously-skip-permissions --continue 'Resume your workflow.'
```

## Listing Tabs

```bash
# Structured output with TAB_ID, POSITION, NAME
zellij action list-tabs
```

## Tab Ownership

You own tabs you created (named after worktrees: `wt-*`). The user owns all other tabs. Never touch tabs you don't own.
