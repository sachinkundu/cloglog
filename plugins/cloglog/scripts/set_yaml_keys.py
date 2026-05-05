#!/usr/bin/env python3
"""Set scalar keys in a YAML config file.

Usage: set_yaml_keys.py <config-path> key1=value1 key2=value2 ...

Each key=value pair is upserted: the line ``key: <old>`` is replaced
with ``key: value``, or the pair is appended when the key is absent.
Lines are matched on the prefix ``^key:``, so any whitespace after the
colon in the original file is normalised to a single space.

Stdlib-only — no PyYAML. Safe against values containing sed delimiter
chars (``&``, ``|``, ``/``, ``\\``) or spaces.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def upsert_keys(config_path: Path, updates: dict[str, str]) -> None:
    """Upsert *updates* into the YAML file at *config_path* (atomic write)."""
    if config_path.exists():
        lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    remaining: dict[str, str] = dict(updates)
    out: list[str] = []

    for line in lines:
        matched_key: str | None = None
        for key in remaining:
            if re.match(rf"^{re.escape(key)}\s*:", line):
                matched_key = key
                break
        if matched_key is not None:
            out.append(f"{matched_key}: {remaining.pop(matched_key)}\n")
        else:
            out.append(line)

    if remaining and out and not out[-1].endswith("\n"):
        out[-1] += "\n"

    for key, value in remaining.items():
        out.append(f"{key}: {value}\n")

    config_path.parent.mkdir(parents=True, exist_ok=True)

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text("".join(out), encoding="utf-8")
    tmp.replace(config_path)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: set_yaml_keys.py <config-path> [key=value ...]\n")
        return 2

    config_path = Path(argv[1])
    updates: dict[str, str] = {}

    for arg in argv[2:]:
        key, sep, value = arg.partition("=")
        if not sep:
            sys.stderr.write(f"error: argument must be key=value, got {arg!r}\n")
            return 2
        if not key:
            sys.stderr.write(f"error: empty key in {arg!r}\n")
            return 2
        updates[key] = value

    upsert_keys(config_path, updates)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
