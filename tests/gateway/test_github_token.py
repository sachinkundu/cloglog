"""Tests for GitHub App token generation and caching.

Mocks JWT signing (the PEM file is not present in CI) and the GitHub
``/app/installations/{id}/access_tokens`` endpoint via respx.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import httpx
import pytest
import respx

from src.gateway import github_token
from src.gateway.github_token import (
    _CLAUDE_APP_ID,
    _CLAUDE_INSTALLATION_ID,
    _CLAUDE_PERMISSIONS,
    get_github_app_token,
    reset_token_cache,
)

_TOKEN_URL = f"https://api.github.com/app/installations/{_CLAUDE_INSTALLATION_ID}/access_tokens"


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    """Reset cached token before and after each test so ordering is irrelevant."""
    reset_token_cache()
    yield
    reset_token_cache()


@pytest.fixture
def fake_jwt() -> str:
    """Patch the internal JWT builder — tests don't need a real PEM."""
    with patch.object(github_token, "_build_jwt", return_value="fake.jwt.value") as m:
        yield m


@pytest.mark.asyncio
async def test_first_call_fetches_token(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    with respx.mock() as mock:
        route = mock.post(_TOKEN_URL).mock(
            return_value=httpx.Response(201, json={"token": "ghs_first"})
        )
        token = await get_github_app_token()

    assert token == "ghs_first"
    assert route.called
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_second_call_within_ttl_returns_cached(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    with respx.mock() as mock:
        route = mock.post(_TOKEN_URL).mock(
            return_value=httpx.Response(201, json={"token": "ghs_cached"})
        )
        token1 = await get_github_app_token()
        token2 = await get_github_app_token()

    assert token1 == token2 == "ghs_cached"
    assert route.call_count == 1  # Only the first call hit the network


@pytest.mark.asyncio
async def test_refreshes_after_ttl_expires(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    """After the cache TTL has elapsed, a subsequent call must mint a fresh token."""
    with respx.mock() as mock:
        route = mock.post(_TOKEN_URL).mock(
            side_effect=[
                httpx.Response(201, json={"token": "ghs_original"}),
                httpx.Response(201, json={"token": "ghs_refreshed"}),
            ]
        )

        # First call populates cache
        assert await get_github_app_token() == "ghs_original"

        # Simulate TTL elapsing by rewinding the cache timestamp
        expired = time.monotonic() - github_token._CACHE_TTL_SECONDS - 1
        github_token._claude_cache.fetched_at = expired

        assert await get_github_app_token() == "ghs_refreshed"

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_reset_token_cache_forces_refresh(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    with respx.mock() as mock:
        route = mock.post(_TOKEN_URL).mock(
            side_effect=[
                httpx.Response(201, json={"token": "ghs_a"}),
                httpx.Response(201, json={"token": "ghs_b"}),
            ]
        )

        assert await get_github_app_token() == "ghs_a"
        reset_token_cache()
        assert await get_github_app_token() == "ghs_b"

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_http_error_is_raised_and_cache_not_poisoned(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    """A failed request must not leave a stale/bad token in the cache."""
    with respx.mock() as mock:
        mock.post(_TOKEN_URL).mock(return_value=httpx.Response(500, json={"message": "boom"}))
        with pytest.raises(httpx.HTTPStatusError):
            await get_github_app_token()

    # Cache stays empty so the next call will try again
    assert github_token._claude_cache.token is None


@pytest.mark.asyncio
async def test_token_request_uses_bearer_jwt_and_permissions(fake_jwt) -> None:  # type: ignore[no-untyped-def]
    """The outgoing request must carry the signed JWT and requested permissions."""
    with respx.mock() as mock:
        route = mock.post(_TOKEN_URL).mock(
            return_value=httpx.Response(201, json={"token": "ghs_permcheck"})
        )
        await get_github_app_token()

    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer fake.jwt.value"
    assert req.headers["Accept"] == "application/vnd.github+json"

    import json as _json

    body = _json.loads(req.content)
    assert body == {"permissions": _CLAUDE_PERMISSIONS}


def test_build_jwt_uses_pem_and_app_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``_build_jwt`` reads the configured PEM and signs with APP_ID."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    pem_path = tmp_path / "github-app.pem"
    pem_path.write_bytes(pem_bytes)

    with patch.object(github_token, "_CLAUDE_PEM", pem_path):
        encoded = github_token._build_jwt(_CLAUDE_APP_ID, pem_path)

    import jwt as _jwt

    decoded = _jwt.decode(encoded, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == _CLAUDE_APP_ID
    assert decoded["exp"] > decoded["iat"]
