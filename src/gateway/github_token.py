"""GitHub App installation token generation with short-term caching.

Extracts the token-minting logic from ``scripts/gh-app-token.py`` into an
async function suitable for use from webhook consumers. Tokens expire after
60 minutes; we cache for 50 to leave a safe refresh buffer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx
import jwt

APP_ID: Final = "3235173"
INSTALLATION_ID: Final = "120404294"
PEM_PATH: Final = Path.home() / ".agent-vm" / "credentials" / "github-app.pem"

_CACHE_TTL_SECONDS: Final = 3000.0  # 50 minutes; GitHub tokens expire at 60
_TOKEN_URL: Final = f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens"
_TOKEN_PERMISSIONS: Final = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "workflows": "write",
}


@dataclass
class _TokenCache:
    token: str | None = None
    fetched_at: float = 0.0


_cache = _TokenCache()


def _build_jwt() -> str:
    """Sign the short-lived JWT used to request installation tokens."""
    private_key = PEM_PATH.read_bytes()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": APP_ID}
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_github_app_token() -> str:
    """Return a cached GitHub App installation token, refreshing if expired."""
    now = time.monotonic()
    if _cache.token is not None and (now - _cache.fetched_at) < _CACHE_TTL_SECONDS:
        return _cache.token

    encoded = _build_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Bearer {encoded}",
                "Accept": "application/vnd.github+json",
            },
            json={"permissions": _TOKEN_PERMISSIONS},
        )
        resp.raise_for_status()
        token: str = resp.json()["token"]

    _cache.token = token
    _cache.fetched_at = now
    return token


def reset_token_cache() -> None:
    """Clear the cached token. Primarily for tests."""
    _cache.token = None
    _cache.fetched_at = 0.0
