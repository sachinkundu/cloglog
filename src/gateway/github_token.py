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

_CACHE_TTL_SECONDS: Final = 3000.0  # 50 minutes; GitHub tokens expire at 60

# ---------------------------------------------------------------------------
# Claude bot (code push, PR creation)
# ---------------------------------------------------------------------------
_CLAUDE_APP_ID: Final = "3235173"
_CLAUDE_INSTALLATION_ID: Final = "120404294"
_CLAUDE_PEM: Final = Path.home() / ".agent-vm" / "credentials" / "github-app.pem"
_CLAUDE_PERMISSIONS: Final = {
    "contents": "write",
    "pull_requests": "write",
    "issues": "write",
    "workflows": "write",
}

# ---------------------------------------------------------------------------
# Codex reviewer bot (posts reviews only)
# ---------------------------------------------------------------------------
_CODEX_APP_ID: Final = "3408174"
_CODEX_INSTALLATION_ID: Final = "124664077"
_CODEX_PEM: Final = Path.home() / ".agent-vm" / "credentials" / "codex-reviewer.pem"
_CODEX_PERMISSIONS: Final = {
    "contents": "read",
    "pull_requests": "write",
}

# ---------------------------------------------------------------------------
# Opencode reviewer bot (posts reviews only). Public identifiers are
# hard-coded to match the _CLAUDE/_CODEX precedent above — the PEM at
# ~/.agent-vm/credentials/opencode-reviewer.pem (mode 0600) is the only
# per-host secret. Operators don't touch .env for this bot; provisioning
# is one `chmod 600` on the PEM. See docs/setup-credentials.md.
# ---------------------------------------------------------------------------
_OPENCODE_APP_ID: Final = "3473952"
_OPENCODE_INSTALLATION_ID: Final = "126333517"
_OPENCODE_PEM: Final = Path.home() / ".agent-vm" / "credentials" / "opencode-reviewer.pem"
_OPENCODE_PERMISSIONS: Final = {
    "contents": "read",
    "pull_requests": "write",
}


@dataclass
class _TokenCache:
    token: str | None = None
    fetched_at: float = 0.0


_claude_cache = _TokenCache()
_codex_cache = _TokenCache()
_opencode_cache = _TokenCache()


def _build_jwt(app_id: str, pem_path: Path) -> str:
    """Sign the short-lived JWT used to request installation tokens."""
    private_key = pem_path.read_bytes()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _get_token(
    app_id: str,
    installation_id: str,
    pem_path: Path,
    permissions: dict[str, str],
    cache: _TokenCache,
) -> str:
    """Return a cached installation token, refreshing if expired."""
    now = time.monotonic()
    if cache.token is not None and (now - cache.fetched_at) < _CACHE_TTL_SECONDS:
        return cache.token

    encoded = _build_jwt(app_id, pem_path)
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {encoded}",
                "Accept": "application/vnd.github+json",
            },
            json={"permissions": permissions},
        )
        resp.raise_for_status()
        token: str = resp.json()["token"]

    cache.token = token
    cache.fetched_at = now
    return token


async def get_github_app_token() -> str:
    """Claude bot token — for pushing code and creating PRs."""
    return await _get_token(
        _CLAUDE_APP_ID,
        _CLAUDE_INSTALLATION_ID,
        _CLAUDE_PEM,
        _CLAUDE_PERMISSIONS,
        _claude_cache,
    )


async def get_codex_reviewer_token() -> str:
    """Codex reviewer bot token — for posting PR reviews."""
    return await _get_token(
        _CODEX_APP_ID,
        _CODEX_INSTALLATION_ID,
        _CODEX_PEM,
        _CODEX_PERMISSIONS,
        _codex_cache,
    )


async def get_opencode_reviewer_token() -> str:
    """Opencode reviewer bot token — for posting PR reviews.

    Raises ``FileNotFoundError`` on a host where the PEM hasn't been
    provisioned. Unlike codex (which has no fallback), the two-stage
    sequencer catches this in ``_review_pr`` and degrades to codex-only.
    """
    return await _get_token(
        _OPENCODE_APP_ID,
        _OPENCODE_INSTALLATION_ID,
        _OPENCODE_PEM,
        _OPENCODE_PERMISSIONS,
        _opencode_cache,
    )


def reset_token_cache() -> None:
    """Clear all cached tokens. Primarily for tests."""
    _claude_cache.token = None
    _claude_cache.fetched_at = 0.0
    _codex_cache.token = None
    _codex_cache.fetched_at = 0.0
    _opencode_cache.token = None
    _opencode_cache.fetched_at = 0.0
