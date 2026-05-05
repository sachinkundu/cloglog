#!/usr/bin/env python3
"""Render a Jinja2 template with literal substitution.

Used by the cloglog launch SKILL to produce ``.cloglog/launch.sh`` and
``task.md`` from the static templates in ``plugins/cloglog/templates/``.

Requires: jinja2
Usage: uv run --with jinja2 "${CLAUDE_PLUGIN_ROOT}/scripts/render_template.py" ...

Always invoke under ``uv run --with jinja2`` so the Jinja2 dependency is
provisioned in an ephemeral env (mirrors the ``gh-app-token.py`` pattern,
T-437/T-354). Plain ``python3 render_template.py`` will ``ModuleNotFoundError``
on any host whose system interpreter doesn't already have Jinja2.

Engine: Jinja2 with ``StrictUndefined`` (T-437). The placeholder syntax
is ``{{ key }}`` where ``key`` matches ``[a-z_][a-z0-9_]*``. Autoescape
is OFF — the outputs are bash and Markdown, not HTML — so values
containing ``&``, ``\\``, ``|``, or newlines round-trip verbatim. The
T-354 metacharacter-escape gotcha (sed splicing ``&``/``\\``/``|``) is
preserved by Jinja2's literal substitution semantics.

Values come from ``--var key=value`` flags or the process environment
(``--var`` wins on conflict).

Usage::

    uv run --with jinja2 "${CLAUDE_PLUGIN_ROOT}/scripts/render_template.py" \\
        --template path/to/template \\
        --output path/to/output \\
        --var key=value [--var key2=value2 ...]

Exit codes:
    0 — rendered cleanly
    1 — at least one ``{{ key }}`` placeholder had no value (strict default)
    2 — argument shape error (malformed ``--var``, missing template, etc.)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from jinja2 import Environment, StrictUndefined
from jinja2.meta import find_undeclared_variables

VAR_KEY_RE = re.compile(r"[a-z_][a-z0-9_]*")


def _env() -> Environment:
    return Environment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )


def render(template_text: str, values: dict[str, str], allow_unset: bool) -> tuple[str, list[str]]:
    env = _env()
    declared = find_undeclared_variables(env.parse(template_text))
    missing = sorted(declared - values.keys())
    if missing and not allow_unset:
        return "", missing
    ctx = {**{k: "" for k in missing}, **values} if allow_unset else values
    return env.from_string(template_text).render(**ctx), missing


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--template", required=True, type=Path, help="Path to template file")
    p.add_argument("--output", required=True, type=Path, help="Path to write rendered output")
    p.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="key=value",
        help="Variable binding (repeatable); also reads from process env",
    )
    p.add_argument(
        "--allow-unset",
        action="store_true",
        help="Render unset {{ key }} as empty string instead of failing",
    )
    args = p.parse_args(argv)

    if not args.template.is_file():
        print(f"render_template: template not found: {args.template}", file=sys.stderr)
        return 2

    values: dict[str, str] = {}
    for kv in args.var:
        if "=" not in kv:
            print(f"render_template: --var must be key=value: {kv!r}", file=sys.stderr)
            return 2
        key, _, val = kv.partition("=")
        if not VAR_KEY_RE.fullmatch(key):
            print(
                f"render_template: --var key must match [a-z_][a-z0-9_]*: {key!r}",
                file=sys.stderr,
            )
            return 2
        values[key] = val

    text = args.template.read_text(encoding="utf-8")
    referenced = find_undeclared_variables(_env().parse(text))
    for key in referenced - values.keys():
        if not VAR_KEY_RE.fullmatch(key):
            continue
        # Try the lower-case key first (the new contract), then the
        # upper-case shape for back-compat with callers that still export
        # `TASK_NUMBER`/`WORKTREE_PATH` etc. into the process env (T-437
        # codex round 2 — preserve the documented env-fallback contract).
        env_val = os.environ.get(key)
        if env_val is None:
            env_val = os.environ.get(key.upper())
        if env_val is not None:
            values[key] = env_val

    rendered, missing = render(text, values, args.allow_unset)

    if missing and not args.allow_unset:
        print(f"render_template: unsubstituted placeholders: {missing}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
