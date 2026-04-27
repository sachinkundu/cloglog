#!/usr/bin/env python3
"""Stdlib-only mini-parser for the worktree_scopes mapping in .cloglog/config.yaml.

Used by plugins/cloglog/hooks/protect-worktree-writes.sh to look up the list
of allowed paths for a given worktree scope without importing PyYAML. The
Phase 0a helper (lib/parse-yaml-scalar.sh) handles top-level scalars via
grep+sed; this parser handles the one nested-mapping site that grep+sed
cannot represent (T-313 / Phase 0b of F-53).

Why stdlib-only: docs/invariants.md:76 forbids ````yaml`` import`` in plugin
hooks because the system python3 plugin hooks run under typically lacks
PyYAML. The previous python-snippet at protect-worktree-writes.sh:52-72
silently swallowed that ImportError and returned an empty scope, dropping
the write-guard on portable hosts.

Supported shapes (anything else raises and exits non-zero — silent
parse-wrong is the failure mode this file exists to prevent):

    worktree_scopes:
      board: [src/board/, tests/board/]            # flow list (production)
      agent:                                       # block list (audit example)
        - src/agent/
        - tests/agent/

Lookup: exact match first, then longest-prefix fallback (matches the
original python snippet so 'frontend-auth' falls through to 'frontend').

Usage:
    parse-worktree-scopes.py <config-path> <scope-name>

Output: comma-separated path list on stdout (no trailing newline when
empty), or empty string when the scope is absent. Exits non-zero on
parse error or missing file so the calling hook fails closed.
"""

from __future__ import annotations

import re
import sys

_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_BLOCK_ITEM_RE = re.compile(r"^-\s+(.+)$")
_INLINE_COMMENT_RE = re.compile(r"\s+#.*$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse(config_path: str) -> dict[str, list[str]]:
    """Return ``{scope_name: [allowed_path, ...]}`` from ``worktree_scopes``.

    Raises ``ValueError`` on any unsupported YAML shape so the caller can
    surface a real error rather than acting on partial data.
    """
    with open(config_path, encoding="utf-8") as fh:
        lines = fh.readlines()

    scopes: dict[str, list[str]] = {}
    in_block = False
    child_indent: int | None = None
    current_key: str | None = None
    current_list: list[str] | None = None

    def flush() -> None:
        nonlocal current_key, current_list
        if current_key is not None and current_list is not None:
            if current_key in scopes:
                raise ValueError(f"duplicate scope key: {current_key!r}")
            scopes[current_key] = current_list
        current_key = None
        current_list = None

    for lineno, raw in enumerate(lines, start=1):
        stripped_line = raw.rstrip("\n").rstrip()
        content = stripped_line.lstrip(" ")
        if not content or content.startswith("#"):
            continue
        indent = len(stripped_line) - len(content)

        if not in_block:
            if indent == 0 and content.startswith("worktree_scopes:"):
                rest = content[len("worktree_scopes:"):].strip()
                if rest and rest != "{}":
                    raise ValueError(
                        f"line {lineno}: worktree_scopes must be a nested mapping, "
                        f"not an inline value ({rest!r})"
                    )
                in_block = True
            continue

        # Inside the worktree_scopes block.
        if indent == 0:
            # Block ended; we don't care about anything after it.
            flush()
            in_block = False
            continue

        if child_indent is None:
            child_indent = indent

        if indent == child_indent:
            flush()
            match = _KEY_RE.match(content)
            if not match:
                raise ValueError(
                    f"line {lineno}: expected `<scope>:` mapping key, got {content!r}"
                )
            key = match.group(1)
            rest = _INLINE_COMMENT_RE.sub("", match.group(2)).strip()
            current_key = key
            if not rest:
                current_list = []
                continue
            flow = re.match(r"^\[(.*)\]$", rest)
            if not flow:
                raise ValueError(
                    f"line {lineno}: scope value must be `[a, b, ...]` flow list "
                    f"or block list on following lines, got {rest!r}"
                )
            items = [_strip_quotes(p) for p in flow.group(1).split(",")]
            current_list = [p for p in items if p]
        elif indent > child_indent:
            if current_key is None:
                raise ValueError(
                    f"line {lineno}: orphan list item under worktree_scopes"
                )
            match = _BLOCK_ITEM_RE.match(content)
            if not match:
                raise ValueError(
                    f"line {lineno}: expected `- <path>` block list item, got {content!r}"
                )
            value = _INLINE_COMMENT_RE.sub("", match.group(1)).strip()
            assert current_list is not None
            current_list.append(_strip_quotes(value))
        else:
            raise ValueError(
                f"line {lineno}: unexpected dedent inside worktree_scopes (indent={indent}, "
                f"child_indent={child_indent})"
            )

    flush()
    return scopes


def lookup(scopes: dict[str, list[str]], scope_name: str) -> list[str]:
    if scope_name in scopes:
        return scopes[scope_name]
    for key in sorted(scopes.keys(), key=len, reverse=True):
        if scope_name.startswith(key):
            return scopes[key]
    return []


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(
            "usage: parse-worktree-scopes.py <config-path> <scope-name>\n"
        )
        return 2
    config_path, scope_name = argv[1], argv[2]
    try:
        scopes = parse(config_path)
    except FileNotFoundError:
        sys.stderr.write(f"config not found: {config_path}\n")
        return 3
    except ValueError as exc:
        sys.stderr.write(f"parse error: {exc}\n")
        return 4
    paths = lookup(scopes, scope_name)
    sys.stdout.write(",".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
