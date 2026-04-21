#!/usr/bin/env bash
# Demo: T-216 + T-243 plugin-doc inbox-path sync + agent_unregistered event backstop.
# Called by `make demo`. No backend dependency — every proof is local, deterministic, and
# captures only reduced summary output (counts, OK/FAIL booleans) so `showboat verify` is
# byte-exact across runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
DEMO_FILE="$REPO_ROOT/docs/demos/${BRANCH//\//-}/demo.md"

cd "$REPO_ROOT"

uvx showboat init "$DEMO_FILE" \
  "Worktree agents now share one inbox path across every plugin doc, and a missed agent_unregistered write no longer disappears — the SessionEnd hook writes a best-effort backstop to the main agent inbox on shutdown."

# ---------------------------------------------------------------------------
# T-216 — plugin docs/skills reference one inbox path
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "T-216 proof 1 — no plugin doc or skill still points at the removed /tmp/cloglog-inbox-* path. Output is the match count (0 means clean)."

uvx showboat exec "$DEMO_FILE" bash \
  'echo "legacy_path_hits_in_plugins=$(grep -rn "/tmp/cloglog-inbox" plugins/ | wc -l | tr -d " ")"'

uvx showboat note "$DEMO_FILE" \
  "T-216 proof 2 — the four plugin files in the T-216 audit scope (worktree-agent.md, claude-md-fragment.md, launch/SKILL.md, github-bot/SKILL.md) each reference the canonical .cloglog/inbox form. Output: one OK per file — capturing per-file booleans rather than a repo-wide count keeps showboat verify byte-exact when future plugin docs add or remove unrelated inbox mentions."

uvx showboat exec "$DEMO_FILE" bash \
  'for f in agents/worktree-agent.md \
            templates/claude-md-fragment.md \
            skills/launch/SKILL.md \
            skills/github-bot/SKILL.md; do
     if grep -q "\.cloglog/inbox" "plugins/cloglog/$f"; then
       echo "${f}=OK"
     else
       echo "${f}=FAIL"
     fi
   done'

# ---------------------------------------------------------------------------
# T-243 — canonical doc carries the agent_unregistered contract
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "T-243 proof 1 — docs/design/agent-lifecycle.md carries the agent_unregistered contract: event name, absolute-paths rule, hook-backstop language. Output: one OK per property, all three required."

uvx showboat exec "$DEMO_FILE" bash \
  'SPEC=docs/design/agent-lifecycle.md
   c_event=$(grep -c "agent_unregistered" "$SPEC")
   c_abs=$(grep -c "must be absolute paths" "$SPEC" || true)
   c_hook=$(grep -c "best_effort_backstop_from_session_end_hook" "$SPEC" || true)
   echo "event_mentioned=$( [[ $c_event -ge 3 ]] && echo OK || echo FAIL )"
   echo "absolute_paths_required=$( [[ $c_abs -ge 1 ]] && echo OK || echo FAIL )"
   echo "hook_backstop_documented=$( [[ $c_hook -ge 1 ]] && echo OK || echo FAIL )"'

# ---------------------------------------------------------------------------
# T-243 — AGENT_PROMPT template in launch skill carries the rule
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "T-243 proof 2 — the AGENT_PROMPT template in the launch skill tells every future worktree agent to emit agent_unregistered before calling unregister_agent."

uvx showboat exec "$DEMO_FILE" bash \
  'SKILL=plugins/cloglog/skills/launch/SKILL.md
   c=$(grep -c "agent_unregistered" "$SKILL")
   c_started=$(grep -c "agent_started" "$SKILL")
   echo "agent_unregistered_in_template=$( [[ $c -ge 1 ]] && echo OK || echo FAIL )"
   echo "agent_started_in_template=$( [[ $c_started -ge 1 ]] && echo OK || echo FAIL )"'

# ---------------------------------------------------------------------------
# T-243 — SessionEnd hook writes the event in a simulated run
# ---------------------------------------------------------------------------

uvx showboat note "$DEMO_FILE" \
  "T-243 proof 3 — run plugins/cloglog/hooks/agent-shutdown.sh against a stub worktree (a git worktree inside a scratch repo) with no CLOGLOG_API_KEY, then grep the stub project-root inbox. Output: one OK per property the backstop must produce."

uvx showboat exec "$DEMO_FILE" bash \
  'HOOK="$PWD/plugins/cloglog/hooks/agent-shutdown.sh"
   TMP=$(mktemp -d)
   trap "rm -rf $TMP" EXIT
   git init -q "$TMP/main"
   git -C "$TMP/main" -c user.email=a@b -c user.name=a commit --allow-empty -m init -q
   # Use the same default branch the real repo uses — the hook greps `main..HEAD`.
   git -C "$TMP/main" branch -M main
   git -C "$TMP/main" worktree add -q "$TMP/wt-sim" -b wt-sim
   git -C "$TMP/wt-sim" -c user.email=a@b -c user.name=a commit --allow-empty -m "T-243 hook backstop for T-216 inbox-path audit" -q
   mkdir -p "$TMP/main/.cloglog"
   : > "$TMP/main/.cloglog/inbox"
   # HOME points at an empty dir so ~/.cloglog/credentials is absent and the hook
   # takes the no-API-KEY path (no real unregister POST during the demo).
   printf "{\"cwd\":\"%s\"}" "$TMP/wt-sim" \
     | env -i HOME="$TMP/empty-home" PATH="$PATH" bash "$HOOK" >/dev/null 2>&1
   INBOX_CONTENT=$(cat "$TMP/main/.cloglog/inbox")
   has_event=$(grep -c "\"type\":\"agent_unregistered\"" "$TMP/main/.cloglog/inbox")
   has_reason=$(grep -c "best_effort_backstop_from_session_end_hook" "$TMP/main/.cloglog/inbox")
   has_worktree=$(grep -c "\"worktree\":\"wt-sim\"" "$TMP/main/.cloglog/inbox")
   has_absolute=$(grep -c "\"work_log\":\"$TMP/wt-sim/shutdown-artifacts/work-log.md\"" "$TMP/main/.cloglog/inbox")
   has_task=$(grep -c "\"T-243\"" "$TMP/main/.cloglog/inbox")
   echo "event_written=$( [[ $has_event -eq 1 ]] && echo OK || echo FAIL )"
   echo "reason_backstop=$( [[ $has_reason -eq 1 ]] && echo OK || echo FAIL )"
   echo "worktree_field_present=$( [[ $has_worktree -eq 1 ]] && echo OK || echo FAIL )"
   echo "artifacts_are_absolute_paths=$( [[ $has_absolute -eq 1 ]] && echo OK || echo FAIL )"
   echo "tasks_completed_parsed_from_git_log=$( [[ $has_task -eq 1 ]] && echo OK || echo FAIL )"'

uvx showboat verify "$DEMO_FILE"
