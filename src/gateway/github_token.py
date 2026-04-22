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

from src.shared.config import settings

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
# Opencode reviewer bot (posts reviews only) — operational onboarding:
# install the GitHub App, download its private key, and place it at
# ~/.agent-vm/credentials/opencode-reviewer.pem (mode 0600). App-id and
# installation-id are read from ``Settings`` (not ``os.environ.get`` — see
# PR #187 round 1 HIGH) so they honour the backend's ``.env`` file alongside
# every other operator-facing setting.
# ---------------------------------------------------------------------------
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


class OpencodeBotNotConfiguredError(RuntimeError):
    """Raised when OPENCODE_APP_ID / OPENCODE_INSTALLATION_ID are unset.

    Callers in the sequencer treat this as the same class of failure as a
    missing PEM — stage A is skipped with a single structured log line.
    """


async def get_opencode_reviewer_token() -> str:
    """Opencode reviewer bot token — for posting PR reviews.

    Raises ``OpencodeBotNotConfiguredError`` if the app-id/installation-id env
    vars are not set; the sequencer catches this and degrades gracefully.
    """
    app_id = settings.opencode_app_id
    installation_id = settings.opencode_installation_id
    if not app_id or not installation_id:
        raise OpencodeBotNotConfiguredError(
            "settings.opencode_app_id and settings.opencode_installation_id must "
            "be set (place them in backend .env or export OPENCODE_APP_ID / "
            "OPENCODE_INSTALLATION_ID — see docs/setup-credentials.md)"
        )
    return await _get_token(
        app_id,
        installation_id,
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
