"""Unit tests for ``src.board.repo_url.normalize_repo_url``."""

from __future__ import annotations

import pytest

from src.board.repo_url import normalize_repo_url

CANONICAL = "https://github.com/owner/repo"


@pytest.mark.parametrize(
    "raw",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/",
        "https://github.com/owner/repo.git/",
        "git@github.com:owner/repo",
        "git@github.com:owner/repo.git",
        "http://github.com/owner/repo",
        "  https://github.com/owner/repo  ",
        "  git@github.com:owner/repo.git  ",
    ],
)
def test_normalize_to_canonical(raw: str) -> None:
    assert normalize_repo_url(raw) == CANONICAL


def test_canonical_is_idempotent() -> None:
    assert normalize_repo_url(CANONICAL) == CANONICAL
    assert normalize_repo_url(normalize_repo_url("git@github.com:owner/repo.git")) == CANONICAL


def test_empty_returns_empty() -> None:
    assert normalize_repo_url("") == ""
    assert normalize_repo_url("   ") == ""


def test_non_github_url_keeps_host_strips_suffixes() -> None:
    """We don't rewrite the host of non-GitHub URLs (silent host
    coercion would erase data), but ``.git`` and trailing slashes are
    still stripped — the canonical form is consistent across hosts."""
    assert normalize_repo_url("https://gitlab.com/owner/repo.git") == (
        "https://gitlab.com/owner/repo"
    )
    assert normalize_repo_url("  https://gitlab.com/owner/repo/  ") == (
        "https://gitlab.com/owner/repo"
    )


def test_endswith_match_works_against_repo_full_name() -> None:
    """The webhook consumer matches a project by
    ``Project.repo_url.endswith(<owner>/<repo>)``. Verify canonical
    storage is compatible with that lookup."""
    assert normalize_repo_url("git@github.com:sachinkundu/antisocial.git").endswith(
        "sachinkundu/antisocial"
    )
