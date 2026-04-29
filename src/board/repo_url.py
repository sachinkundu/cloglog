"""Canonicalize GitHub repository URLs.

The ``find_project_by_repo`` lookup at ``src/board/repository.py`` matches a
project row by ``Project.repo_url.endswith(repo_full_name)`` — so a row that
stores ``https://github.com/owner/repo.git`` (with the ``.git`` suffix) or
``git@github.com:owner/repo.git`` (SSH form) won't match the
``owner/repo`` argument the webhook consumer hands it. Normalizing every
write through this helper keeps stored URLs in the single canonical
``https://github.com/<owner>/<repo>`` shape so the lookup always hits.

The helper is stdlib-only and idempotent — feeding canonical input back
through ``normalize_repo_url`` returns it unchanged.
"""

from __future__ import annotations

_GITHUB_HTTPS_PREFIX = "https://github.com/"
_GITHUB_HTTP_PREFIX = "http://github.com/"
_GITHUB_SSH_PREFIX = "git@github.com:"


def normalize_repo_url(url: str) -> str:
    """Return the canonical ``https://github.com/<owner>/<repo>`` form.

    - Strips surrounding whitespace.
    - Converts SSH form (``git@github.com:owner/repo``) to HTTPS.
    - Strips a trailing ``.git`` suffix.
    - Strips a trailing slash.
    - Non-GitHub hosts keep their host (we don't silently rewrite the
      host — that would erase data), but ``.git`` / trailing-slash
      stripping still runs.
    - The empty string round-trips to empty.
    """
    s = url.strip()
    if not s:
        return ""

    if s.startswith(_GITHUB_SSH_PREFIX):
        s = _GITHUB_HTTPS_PREFIX + s[len(_GITHUB_SSH_PREFIX) :]
    elif s.startswith(_GITHUB_HTTP_PREFIX):
        s = _GITHUB_HTTPS_PREFIX + s[len(_GITHUB_HTTP_PREFIX) :]

    # Loop: ``.git/`` and ``/.git`` and ``.git`` all collapse to the same
    # canonical form. A single pass would leave ``repo.git/`` as
    # ``repo.git`` (trailing slash stripped first means .git is gone) or
    # ``repo/`` (.git stripped first leaves a trailing slash) — neither
    # matches canonical bytes.
    while s.endswith("/") or s.endswith(".git"):
        if s.endswith("/"):
            s = s[:-1]
        if s.endswith(".git"):
            s = s[: -len(".git")]

    return s
