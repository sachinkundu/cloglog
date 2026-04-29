#!/usr/bin/env python3
"""Generate a GitHub App installation token.

Requires: PyJWT[crypto], requests
Usage: uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py"

Resolution order for GH_APP_ID / GH_APP_INSTALLATION_ID (T-348):
  1. Environment variables (highest priority — preserves operator overrides).
  2. `.cloglog/local.yaml` in the project root (gitignored, host-local — the
     preferred path on a multi-operator clone where each operator installs
     the App into their own org/repo and gets a distinct Installation ID).
  3. `.cloglog/config.yaml` in the project root (tracked — fallback for
     single-operator repos where bot identity is the same across clones).

The PEM private key must be at ~/.agent-vm/credentials/github-app.pem
(not checked into the repo — it's a secret).
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import jwt
import requests


def _project_root() -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out.decode().strip())


def _read_scalar(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.*?)\s*(#.*)?$")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            m = pattern.match(line)
            if m:
                value = m.group(1).strip()
                # Strip surrounding quotes (matches the bash grep+sed shape).
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ('"', "'")
                ):
                    value = value[1:-1]
                return value
    except OSError:
        return ""
    return ""


def _resolve(key: str) -> str:
    env = os.environ.get(key, "").strip()
    if env:
        return env
    root = _project_root()
    if root is None:
        return ""
    yaml_key = key.lower()
    for filename in ("local.yaml", "config.yaml"):
        value = _read_scalar(root / ".cloglog" / filename, yaml_key)
        if value:
            return value
    return ""


APP_ID = _resolve("GH_APP_ID")
INSTALLATION_ID = _resolve("GH_APP_INSTALLATION_ID")
PEM_PATH = os.path.expanduser("~/.agent-vm/credentials/github-app.pem")

_HINT = (
    "    1. export the env var, OR\n"
    "    2. add `gh_app_id: \"<id>\"` / `gh_app_installation_id: \"<id>\"` to\n"
    "       .cloglog/local.yaml (gitignored, preferred — host-local).\n"
    "    See plugins/cloglog/docs/setup-credentials.md for details."
)

if not APP_ID:
    print(
        f"Error: GH_APP_ID is required (env or .cloglog/local.yaml).\n{_HINT}",
        file=sys.stderr,
    )
    sys.exit(1)
if not INSTALLATION_ID:
    print(
        f"Error: GH_APP_INSTALLATION_ID is required (env or .cloglog/local.yaml).\n{_HINT}",
        file=sys.stderr,
    )
    sys.exit(1)
if not os.path.exists(PEM_PATH):
    print(f"Error: PEM file not found at {PEM_PATH}", file=sys.stderr)
    sys.exit(1)

with open(PEM_PATH, "rb") as f:
    private_key = f.read()

now = int(time.time())
payload = {"iat": now - 60, "exp": now + 600, "iss": APP_ID}
encoded = jwt.encode(payload, private_key, algorithm="RS256")

r = requests.post(
    f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
    headers={"Authorization": f"Bearer {encoded}", "Accept": "application/vnd.github+json"},
    json={
        "permissions": {"contents": "write", "pull_requests": "write", "issues": "write", "workflows": "write"},
    },
)

if r.status_code != 201:
    print(f"Error: {r.status_code} {r.text}", file=sys.stderr)
    sys.exit(1)

print(r.json()["token"])
