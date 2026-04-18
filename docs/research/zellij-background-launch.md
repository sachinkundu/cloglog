# Research: Reliable Background Agent Launch in Zellij

**Task:** T-210  
**Date:** 2026-04-18  
**Zellij version tested:** 0.44.0

---

## Problem Statement

The current agent launch sequence is flaky in two ways:

1. **`list-clients` doesn't see new shell panes** — it only returns panes with active Claude sessions, so `awk 'NR==2{print $2}'` grabs the wrong pane-id (usually the main agent's own pane).
2. **Tab switching during launch steals focus** — `new-tab` jumps focus to the new tab, `go-to-tab-name` returns it, but there is a visible flash and a race condition if the user clicks during the sequence.

---

## What Zellij 0.44.0 Natively Supports

### `zellij action new-tab` — returns its own ID

```
USAGE: zellij action new-tab [OPTIONS] [-- <INITIAL_COMMAND>...]
Returns: The created tab's ID as a single number on stdout
```

Key flags:
- `-- <INITIAL_COMMAND>...` — optional command to run in the tab's initial pane
- `--name <NAME>` — sets the tab name
- `--start-suspended` — defers command execution until first keypress
- **No `--no-focus` / `--background` flag exists**

### `zellij action new-pane` — returns pane ID

```
USAGE: zellij action new-pane [OPTIONS] [-- <COMMAND>...]
Returns: Created pane ID (format: terminal_<id>)
```

Key flags:
- `-- <COMMAND>...` — starts a command directly in the new pane
- **No `--no-focus` / `--background` flag** — always steals focus
- `--start-suspended` — defers execution

### `zellij run` — shorthand for new-pane with command

```
USAGE: zellij run [OPTIONS] [--] <COMMAND>...
Returns: Created pane ID (format: terminal_<id>)
```

Identical focus behavior to `new-pane`. No background mode.

### `zellij action current-tab-info` — returns current tab ID

```
name: Tab #1
id: 0
position: 0
```

### `zellij action go-to-tab-by-id <ID>` — navigate to tab by stable ID

Stable numeric ID, not affected by tab renames or reordering.

### `write-chars` / `write` — pane-id only

`zellij action write-chars --pane-id <ID>` only accepts numeric pane IDs. There is no pane-name targeting. This is tracked as [GitHub issue #3061](https://github.com/zellij-org/zellij/issues/3061) (unresolved).

### Layout files — can pre-configure commands, but resurrection breaks them

Layout files support `command` panes. However, session resurrection forces `start_suspended=true` on all command panes to prevent unintended auto-execution ([issue #4754](https://github.com/zellij-org/zellij/issues/4754)), making them unsuitable for reliable programmatic launch.

### Background session workaround

Create a headless zellij session, then drive it via CLI:
```bash
zellij attach --create-background -s agents
zellij -s agents action new-pane -- bash launcher.sh
```
This avoids focus steal entirely, but agents run in a separate session — the user must `zellij attach -s agents` to see them. Not ideal for the "navigate to tab" UX.

---

## Root Cause of Current Flakiness

The current SKILL.md uses:
```bash
PANE_ID=$(zellij action list-clients 2>&1 | awk 'NR==2{print $2}')
```

`list-clients` only shows panes where Claude Code is **already running**. A freshly created shell pane (before Claude launches) is invisible to `list-clients`. The `awk 'NR==2'` grabs the second client — which is usually the main agent's own pane ID. This sends the launch command to the wrong pane.

---

## Recommended Approach: Fix in Zellij (No Migration Needed)

`new-tab` returns its tab ID on stdout. `new-pane` returns its pane ID. Neither requires `list-clients`. The fix eliminates the flaky ID-guessing entirely.

### New launch sequence

```bash
# 1. Capture current tab's stable ID
CURRENT_TAB_ID=$(zellij action current-tab-info 2>&1 | awk '/^id:/ {print $2}')

# 2. Write a launcher script to avoid shell-quoting issues with claude's prompt
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << EOF
#!/bin/bash
cd "${WORKTREE_PATH}"
exec claude --dangerously-skip-permissions 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.'
EOF
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# 3. Create the tab with command already embedded — no write-chars needed
#    (steals focus briefly, but immediately returned in step 4)
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh"

# 4. Return focus to original tab immediately
zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

### Why this works

- **No `list-clients`** — command is embedded in `new-tab`, not sent via `write-chars`
- **No pane ID needed** — `new-tab -- bash launcher.sh` starts Claude directly; nothing to write later
- **No race condition on pane ID** — ID lookup is eliminated entirely
- **Focus stolen only briefly** — `go-to-tab-by-id` immediately returns focus; user sees a flash but not a lingering redirect
- **Launcher script avoids quoting hell** — shell variables expand once at write-time, no nested quote escaping

The tab still exists for the user to navigate to when desired. Claude is already running when they arrive.

---

## Why Not Switch to tmux

tmux's `new-window -d` genuinely avoids focus stealing (the `-d` flag keeps the current window focused). `send-keys -t <name>` targets by name without numeric IDs. For a pure programmatic launcher, tmux is cleaner.

**However, the recommended zellij fix above is sufficient.** The flakiness was never about focus stealing — it was about `list-clients` returning wrong pane IDs. Eliminating `write-chars` removes the problem entirely. No migration needed.

A tmux migration would require users to install tmux alongside zellij, change how they view agent windows (different keybindings, different mental model), and add complexity for no practical gain over the embedded-command approach.

**Verdict: Stay with zellij. Fix the ID-guessing by using the embedded command.**

---

## Concrete Changes Needed in `plugins/cloglog/skills/launch/SKILL.md`

Replace Step **4e** entirely. The current sequence (new-tab → sleep → list-clients → go-to-tab-name → write-chars → write Enter) should become:

**Old (Step 4e):**
```bash
CURRENT_TAB=$(zellij action query-tab-names 2>&1 | head -1)
zellij action new-tab --name "${WORKTREE_NAME}"
sleep 0.5
PANE_ID=$(zellij action list-clients 2>&1 | awk 'NR==2{print $2}')
zellij action go-to-tab-name "${CURRENT_TAB}"
sleep 0.3
zellij action write-chars --pane-id "${PANE_ID}" "cd ${WORKTREE_PATH} && claude ..."
sleep 0.3
zellij action write --pane-id "${PANE_ID}" 13
```

**New (Step 4e):**
```bash
# Capture current tab's stable numeric ID
CURRENT_TAB_ID=$(zellij action current-tab-info 2>&1 | awk '/^id:/ {print $2}')

# Write launcher script (avoids quoting issues in inline commands)
cat > "${WORKTREE_PATH}/.cloglog/launch.sh" << EOF
#!/bin/bash
cd "${WORKTREE_PATH}"
exec claude --dangerously-skip-permissions 'Read ${WORKTREE_PATH}/AGENT_PROMPT.md and begin.'
EOF
chmod +x "${WORKTREE_PATH}/.cloglog/launch.sh"

# Create tab with command embedded — no write-chars, no list-clients, no sleep
zellij action new-tab --name "${WORKTREE_NAME}" -- bash "${WORKTREE_PATH}/.cloglog/launch.sh"

# Return focus immediately
zellij action go-to-tab-by-id "${CURRENT_TAB_ID}"
```

Remove the note about `list-clients` being unreliable — it will no longer be used. Remove the `--cwd` caveat (still valid but irrelevant to this approach). Add a note that `new-tab -- <command>` starts the command in the tab's initial pane directly.

---

## Summary

| Approach | Focus steal | ID reliability | Complexity |
|---|---|---|---|
| Current (list-clients + write-chars) | Yes (2 switches) | Broken | High |
| **new-tab + embedded command** | Brief (1 switch back) | Eliminated | Low |
| Background zellij session | None | N/A | High (dual sessions) |
| tmux migration | None | Excellent | High (tool migration) |

**Recommendation: Use `new-tab -- bash launcher.sh` + `go-to-tab-by-id`. Two-line change in SKILL.md, eliminates all flakiness.**
