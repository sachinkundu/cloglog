# When the launch skill spawns a worktree agent, its 4c snippet now uses an absolute ${WORKTREE_PATH} so the main agent stays anchored in the main clone — no cwd drift into the worktree it just created.

*2026-04-24T07:04:31Z by Showboat 0.6.1*
<!-- showboat-id: f4057007-8e04-4fe1-9126-2cfbc2ad6d91 -->

Before T-284, step 4c invoked '.cloglog/on-worktree-create.sh' as a bare relative path. A main agent peeling that one-liner into a single Bash call had to prepend 'cd <worktree>' to satisfy the test, and the Bash tool's shell persists cwd between calls — so every subsequent main-agent command then ran inside the worktree's tree, looking like cross-contamination of main.

Proof 1: the bash block under '### 4c' contains zero bare-relative invocations of on-worktree-create.sh.

```bash
python3 -c "
import re, pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
m = re.search(r\"### 4c\\..*?\\n\`\`\`bash\\n(.*?)\\n\`\`\`\", src, flags=re.DOTALL)
snippet = m.group(1)
bad = re.findall(r\"(?<![/}])\\.cloglog/on-worktree-create\\.sh\", snippet)
print(f\"bare-relative invocations in 4c bash block: {len(bad)}\")
"
```

```output
bare-relative invocations in 4c bash block: 0
```

Proof 2: the snippet uses the absolute ${WORKTREE_PATH}/.cloglog/on-worktree-create.sh path.

```bash
python3 -c "
import pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
needle = chr(34) + chr(36) + \"{WORKTREE_PATH}/.cloglog/on-worktree-create.sh\" + chr(34)
print(f\"absolute invocations in skill: {src.count(needle)}\")
"
```

```output
absolute invocations in skill: 2
```

Proof 3: no 'cd' command anywhere in the 4c bash block — the snippet is safe to peel out into a single Bash call without prepending anything.

```bash
python3 -c "
import re, pathlib
src = pathlib.Path(\"plugins/cloglog/skills/launch/SKILL.md\").read_text(encoding=\"utf-8\")
m = re.search(r\"### 4c\\..*?\\n\`\`\`bash\\n(.*?)\\n\`\`\`\", src, flags=re.DOTALL)
snippet = m.group(1)
hit = re.search(r\"(^|[\\s;&|])cd\\s\", snippet)
print(f\"cd-into-worktree commands in 4c bash block: {0 if hit is None else 1}\")
"
```

```output
cd-into-worktree commands in 4c bash block: 0
```

Proof 4: the three pin tests under tests/plugins/test_launch_skill_uses_abs_paths.py pass. Imported in-process to avoid pytest's session-autouse Postgres fixture (CLAUDE.md: 'Demo scripts must not call uv run pytest').

```bash
python3 -c "
import sys
sys.path.insert(0, \"tests\")
import plugins.test_launch_skill_uses_abs_paths as t
t.test_launch_skill_4c_uses_absolute_on_worktree_create_path()
t.test_launch_skill_4c_has_no_relative_invocation_or_cd()
t.test_launch_skill_4c_warns_against_cd_into_worktree()
print(\"3 pin assertions passed\")
"
```

```output
3 pin assertions passed
```

After T-284: the 4c snippet is anchored on ${WORKTREE_PATH} and the prose explicitly warns against cd-ing into the new worktree. A future main agent peeling the snippet into a single Bash call invokes the script with an absolute path, no shell-state drift, and the pin tests fail loudly if anyone re-introduces the relative form.
