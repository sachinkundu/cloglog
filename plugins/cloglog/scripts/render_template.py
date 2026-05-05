#!/usr/bin/env python3
"""Render a placeholder template via literal string substitution.

Used by the cloglog launch SKILL to produce ``.cloglog/launch.sh`` and
``task.md`` from the static templates in ``plugins/cloglog/templates/``.

Why a script instead of a SKILL-embedded heredoc + sed pipeline:
the prior shape (T-353/T-354) escaped sed replacement metacharacters
(``&``, ``\\``, ``|``) inside a bash helper whose ``$1`` reference was
lost when the SKILL block crossed the LLM-agent → bash boundary,
producing empty escapes and silently corrupted renderings (literal
``/AGENT_PROMPT.md`` at filesystem root in the agent's prompt). Python's
``str.replace`` is literal — no metacharacter has special meaning — so
adversarial inputs (``R&D follow-up``, paths under ``~/R&D/``, titles
containing the chosen sed delimiter) round-trip verbatim.

The placeholder syntax is ``@@KEY@@`` where ``KEY`` matches
``[A-Z_][A-Z0-9_]*``. Values come from ``--var KEY=VALUE`` flags or the
process environment (``--var`` wins on conflict). Multi-line values are
supported because replacement is a single ``str.replace`` call per key
— no need for sed's ``r FILE`` ``d`` dance.

Usage::

    python3 render_template.py \\
        --template path/to/template \\
        --output path/to/output \\
        --var KEY=VALUE [--var KEY2=VALUE2 ...]

Exit codes:
    0 — rendered cleanly
    1 — at least one ``@@KEY@@`` placeholder had no value (strict default)
    2 — argument shape error (malformed ``--var``, missing template, etc.)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"@@([A-Z_][A-Z0-9_]*)@@")


def render(template_text: str, values: dict[str, str], allow_unset: bool) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key in values:
            return values[key]
        env = os.environ.get(key)
        if env is not None:
            return env
        missing.append(key)
        return "" if allow_unset else match.group(0)

    return PLACEHOLDER_RE.sub(sub, template_text), missing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--template", required=True, type=Path, help="Path to template file")
    p.add_argument("--output", required=True, type=Path, help="Path to write rendered output")
    p.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Variable binding (repeatable); also reads from process env",
    )
    p.add_argument(
        "--allow-unset",
        action="store_true",
        help="Render unset @@KEY@@ as empty string instead of failing",
    )
    args = p.parse_args(argv)

    if not args.template.is_file():
        print(f"render_template: template not found: {args.template}", file=sys.stderr)
        return 2

    values: dict[str, str] = {}
    for kv in args.var:
        if "=" not in kv:
            print(f"render_template: --var must be KEY=VALUE: {kv!r}", file=sys.stderr)
            return 2
        key, _, val = kv.partition("=")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            print(f"render_template: --var key must match [A-Z_][A-Z0-9_]*: {key!r}", file=sys.stderr)
            return 2
        values[key] = val

    text = args.template.read_text(encoding="utf-8")
    rendered, missing = render(text, values, args.allow_unset)

    if missing and not args.allow_unset:
        unique = sorted(set(missing))
        print(
            f"render_template: unsubstituted placeholders: {unique}",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
