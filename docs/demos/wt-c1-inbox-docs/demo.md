# Worktree agents now share one inbox path across every plugin doc, and a missed agent_unregistered write no longer disappears — the SessionEnd hook writes a best-effort backstop to the main agent inbox on shutdown.

*2026-04-20T17:13:25Z by Showboat 0.6.1*
<!-- showboat-id: da25f7c3-8485-4f7d-b995-ea43bac713b9 -->

T-216 proof 1 — no plugin doc or skill still points at the removed /tmp/cloglog-inbox-* path. Output is the match count (0 means clean).

```bash
echo "legacy_path_hits_in_plugins=$(grep -rn "/tmp/cloglog-inbox" plugins/ | wc -l | tr -d " ")"
```

```output
legacy_path_hits_in_plugins=0
```

T-216 proof 2 — every plugin doc that talks about the inbox now uses the canonical <worktree_path>/.cloglog/inbox form. Output is the number of files referencing the canonical path.

```bash
echo "canonical_path_files=$(grep -rl "\.cloglog/inbox" plugins/ | wc -l | tr -d " ")"
```

```output
canonical_path_files=8
```

T-243 proof 1 — docs/design/agent-lifecycle.md carries the agent_unregistered contract: event name, absolute-paths rule, hook-backstop language. Output: one OK per property, all three required.

```bash
SPEC=docs/design/agent-lifecycle.md
   c_event=$(grep -c "agent_unregistered" "$SPEC")
   c_abs=$(grep -c "must be absolute paths" "$SPEC" || true)
   c_hook=$(grep -c "best_effort_backstop_from_session_end_hook" "$SPEC" || true)
   echo "event_mentioned=$( [[ $c_event -ge 3 ]] && echo OK || echo FAIL )"
   echo "absolute_paths_required=$( [[ $c_abs -ge 1 ]] && echo OK || echo FAIL )"
   echo "hook_backstop_documented=$( [[ $c_hook -ge 1 ]] && echo OK || echo FAIL )"
```

```output
event_mentioned=OK
absolute_paths_required=OK
hook_backstop_documented=OK
```

T-243 proof 2 — the AGENT_PROMPT template in the launch skill tells every future worktree agent to emit agent_unregistered before calling unregister_agent.

```bash
SKILL=plugins/cloglog/skills/launch/SKILL.md
   c=$(grep -c "agent_unregistered" "$SKILL")
   c_started=$(grep -c "agent_started" "$SKILL")
   echo "agent_unregistered_in_template=$( [[ $c -ge 1 ]] && echo OK || echo FAIL )"
   echo "agent_started_in_template=$( [[ $c_started -ge 1 ]] && echo OK || echo FAIL )"
```

```output
agent_unregistered_in_template=OK
agent_started_in_template=OK
```

T-243 proof 3 — run plugins/cloglog/hooks/agent-shutdown.sh against a stub worktree (a git worktree inside a scratch repo) with no CLOGLOG_API_KEY, then grep the stub project-root inbox. Output: one OK per property the backstop must produce.

```bash
HOOK="$PWD/plugins/cloglog/hooks/agent-shutdown.sh"
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
   echo "tasks_completed_parsed_from_git_log=$( [[ $has_task -eq 1 ]] && echo OK || echo FAIL )"
```

```output
event_written=OK
reason_backstop=OK
worktree_field_present=OK
artifacts_are_absolute_paths=OK
tasks_completed_parsed_from_git_log=OK
```
