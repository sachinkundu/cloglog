# Learnings — T-312

Durable, non-obvious gotchas discovered during this task. Candidates for the
"Plugin hooks: YAML parsing" section of `CLAUDE.md`.

## Absence-pins on antipattern substrings collide with documentation

A naive absence-pin that asserts `"import yaml" not in body` blocks every comment that *names* the antipattern in prose ("do NOT reintroduce `import yaml`"). The first quality-gate run failed not because the helper used PyYAML — it didn't — but because the helper's own warning comment contained the substring. Two ways out:

1. Re-word warnings to use a non-literal phrase (e.g. "the python YAML lib"), keeping the absence-pin trivial.
2. Make the absence-pin executable-form-aware (regex against `python3 -c "..."` blocks containing `import yaml`).

Picked (1) because it keeps the test trivial and the comment still readable. (2) is correct in principle but adds regex maintenance.

**Generalises to:** any "forbidden substring" pin where docs may legitimately reference the forbidden form. Decide upfront whether the pin is on text or on executable code.

## launch.sh template is a heredoc, so escaping multiplies

The launch SKILL.md emits `.cloglog/launch.sh` via `cat > ... << EOF` with an UNQUOTED EOF. Inside that heredoc:
- `${VAR}` is expanded at render time.
- `\$VAR` becomes `$VAR` in the rendered file.
- `\\` becomes `\` (line-continuation backslashes need `\\` in the template).
- `` \` `` becomes `` ` ``.

I initially tried `tr -d '"'"'"'"'"'"''` (the existing 6-char "strip both quote types" idiom) inside the heredoc. The result rendered with too many quotes because the heredoc treats the chars literally with no shell-quoting collapse. The simpler form `tr -d '"' | tr -d "'"` survives the heredoc untouched and is unambiguous.

**Generalises to:** any time you template shell into shell, simplify the inner script to the dumbest possible form before adding heredoc-escape on top.

## Launch.sh runs without `CLAUDE_PLUGIN_ROOT`

The hook scripts at `plugins/cloglog/hooks/*.sh` can resolve `lib/parse-yaml-scalar.sh` via `BASH_SOURCE`-relative pathing because they're invoked by Claude Code from the plugin tree. But the *generated* `.cloglog/launch.sh` is a standalone bash exec spawned inside the worktree by the launch flow — it has no `CLAUDE_PLUGIN_ROOT`, no plugin tree on disk near it, and the helper might live at `~/.claude/plugins/...` or some other host-specific path. Sourcing the helper there is brittle; inlining a faithful copy of the same grep+sed shape (with a pin asserting the shape) is the durable choice.

**Generalises to:** when a plugin hook generates an artifact that runs outside the plugin's own runtime, prefer self-contained inlined logic over sourcing — and pin the shape so drift is caught.
