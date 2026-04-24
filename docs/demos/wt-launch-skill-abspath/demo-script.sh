#!/usr/bin/env bash
# Demo: launch skill 4c uses absolute paths so the main agent doesn't drift
# into the worktree it just spawned (T-284).
# Called by `make demo` (server + DB are running but this demo doesn't need them).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
DEMO_FILE="$REPO_ROOT/docs/demos/${BRANCH//\//-}/demo.md"

# `uvx showboat init` refuses to overwrite an existing file.
rm -f "$DEMO_FILE"
uvx showboat init "$DEMO_FILE" \
  "When the launch skill spawns a worktree agent, its 4c snippet now uses an absolute \${WORKTREE_PATH} so the main agent stays anchored in the main clone — no cwd drift into the worktree it just created."

# ---------- Why ----------
uvx showboat note "$DEMO_FILE" \
  "Before T-284, step 4c invoked '.cloglog/on-worktree-create.sh' as a bare relative path. A main agent peeling that one-liner into a single Bash call had to prepend 'cd <worktree>' to satisfy the test, and the Bash tool's shell persists cwd between calls — so every subsequent main-agent command then ran inside the worktree's tree, looking like cross-contamination of main."

# ---------- Proof 1: the OLD relative form is gone from the bash block ----------
uvx showboat note "$DEMO_FILE" \
  "Proof 1: the bash block under '### 4c' contains zero bare-relative invocations of on-worktree-create.sh."

uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "
import re, pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
m = re.search(r\"### 4c\\..*?\\n\`\`\`bash\\n(.*?)\\n\`\`\`\", src, flags=re.DOTALL)
snippet = m.group(1)
bad = re.findall(r\"(?<![/}])\\.cloglog/on-worktree-create\\.sh\", snippet)
print(f\"bare-relative invocations in 4c bash block: {len(bad)}\")
"'

# ---------- Proof 2: the NEW absolute form IS present ----------
uvx showboat note "$DEMO_FILE" \
  "Proof 2: the snippet uses the absolute \${WORKTREE_PATH}/.cloglog/on-worktree-create.sh path."

uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "
import pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
needle = chr(34) + chr(36) + \"{WORKTREE_PATH}/.cloglog/on-worktree-create.sh\" + chr(34)
print(f\"absolute invocations in skill: {src.count(needle)}\")
"'

# ---------- Proof 3: the bash block has no `cd` either ----------
uvx showboat note "$DEMO_FILE" \
  "Proof 3: no 'cd' command anywhere in the 4c bash block — the snippet is safe to peel out into a single Bash call without prepending anything."

uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "
import re, pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
m = re.search(r\"### 4c\\..*?\\n\`\`\`bash\\n(.*?)\\n\`\`\`\", src, flags=re.DOTALL)
snippet = m.group(1)
hit = re.search(r\"(^|[\\s;&|])cd\\s\", snippet)
print(f\"cd-into-worktree commands in 4c bash block: {0 if hit is None else 1}\")
"'

# ---------- Proof 4: the pin tests run green (in-process, conftest-free) ----------
uvx showboat note "$DEMO_FILE" \
  "Proof 4: the three pin tests under tests/plugins/test_launch_skill_uses_abs_paths.py pass. Imported in-process to avoid pytest's session-autouse Postgres fixture (CLAUDE.md: 'Demo scripts must not call uv run pytest')."

uvx showboat exec "$DEMO_FILE" bash \
  'python3 -c "
import sys
sys.path.insert(0, \"tests\")
import plugins.test_launch_skill_uses_abs_paths as t
t.test_launch_skill_4c_uses_absolute_on_worktree_create_path()
t.test_launch_skill_4c_has_no_relative_invocation_or_cd()
t.test_launch_skill_4c_warns_against_cd_into_worktree()
print(\"3 pin assertions passed\")
"'

# ---------- After ----------
uvx showboat note "$DEMO_FILE" \
  "After T-284: the 4c snippet is anchored on \${WORKTREE_PATH} and the prose explicitly warns against cd-ing into the new worktree. A future main agent peeling the snippet into a single Bash call invokes the script with an absolute path, no shell-state drift, and the pin tests fail loudly if anyone re-introduces the relative form."

uvx showboat verify "$DEMO_FILE"
