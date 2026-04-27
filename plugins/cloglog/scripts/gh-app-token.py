#!/usr/bin/env python3
"""Generate a GitHub App installation token.

Requires: PyJWT[crypto], requests
Usage: uv run --with "PyJWT[crypto]" --with requests "${CLAUDE_PLUGIN_ROOT}/scripts/gh-app-token.py"

Environment variables (required):
  GH_APP_ID              — GitHub App ID (numeric string, visible on the App settings page)
  GH_APP_INSTALLATION_ID — GitHub App Installation ID (visible on the installation detail page
                            at https://github.com/settings/installations/<id>)

The PEM private key must be at ~/.agent-vm/credentials/github-app.pem
(not checked into the repo — it's a secret).
"""

import os
import sys
import time

import jwt
import requests

APP_ID = os.environ.get("GH_APP_ID", "")
INSTALLATION_ID = os.environ.get("GH_APP_INSTALLATION_ID", "")
PEM_PATH = os.path.expanduser("~/.agent-vm/credentials/github-app.pem")

if not APP_ID:
    print("Error: GH_APP_ID environment variable is required", file=sys.stderr)
    sys.exit(1)
if not INSTALLATION_ID:
    print("Error: GH_APP_INSTALLATION_ID environment variable is required", file=sys.stderr)
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
