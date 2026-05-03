"""T-388 pin: DATABASE_URL is required, no silent fallback to a shared DB.

Silent-failure invariant: if `Settings` (or alembic) ever regrows a default
`database_url`, a worktree / dev / prod backend started without an explicit
`DATABASE_URL` would silently connect to whatever DB the default points at.
That has historically meant worktree migrations bleeding into the dev or
prod `cloglog` database. This test runs python in a clean subprocess with
no `.env` and asserts the failure is loud.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    # Block pydantic-settings from picking up a stray .env in cwd.
    env["PWD"] = str(REPO_ROOT)
    return env


def test_settings_raises_without_database_url(tmp_path: Path) -> None:
    """Importing `src.shared.config` must fail loud when DATABASE_URL is unset.

    The module-level `settings = Settings()` is the chokepoint — every
    request, alembic invocation, and worker import passes through it. A
    missing `DATABASE_URL` must surface as a `ValidationError` naming the
    `database_url` field, not as a silent fallback to a hard-coded URL.
    """
    script = (
        "import sys, traceback\n"
        "try:\n"
        "    import src.shared.config  # noqa: F401\n"
        "except Exception:\n"
        "    tb = traceback.format_exc()\n"
        "    if 'ValidationError' in tb and 'database_url' in tb.lower():\n"
        "        print('OK')\n"
        "        sys.exit(0)\n"
        "    print('FAIL: wrong error shape:\\n' + tb)\n"
        "    sys.exit(2)\n"
        "print('FAIL: import succeeded — Settings() did not raise')\n"
        "sys.exit(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=_clean_env(),
        cwd=tmp_path,  # cwd has no .env, so pydantic-settings finds no env file
    )
    assert result.returncode == 0, (
        f"Importing src.shared.config without DATABASE_URL must raise "
        f"ValidationError naming database_url. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_alembic_ini_has_no_default_database_url() -> None:
    """alembic.ini must not carry a real `sqlalchemy.url` default.

    The default used to be the prod DB (`cloglog`). Any value here is a
    silent-fallback risk because alembic uses it when the env var is unset.
    """
    text = (REPO_ROOT / "alembic.ini").read_text()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("sqlalchemy.url"):
            value = stripped.split("=", 1)[1].strip()
            assert value == "", (
                f"alembic.ini sqlalchemy.url must be empty (T-388 silent-"
                f"fallback invariant), got: {value!r}"
            )


def test_alembic_env_uses_settings_database_url() -> None:
    """`src/alembic/env.py` must source the URL from `Settings`, not a default.

    `Settings` is the single chokepoint that raises on missing DATABASE_URL,
    so alembic must funnel through it. A regression that re-introduces a
    raw `os.environ.get("DATABASE_URL", "<some-default>")` here would
    silently re-enable the shared-DB fallback.
    """
    text = (REPO_ROOT / "src" / "alembic" / "env.py").read_text()
    assert "from src.shared.config import settings" in text, (
        "alembic env.py must import Settings so the .env / required-field "
        "check is shared with the application."
    )
    assert "settings.database_url" in text, (
        "alembic env.py must set sqlalchemy.url from settings.database_url."
    )
    # Defence-in-depth: forbid the old shape `os.environ.get("DATABASE_URL", ...)`
    # with a default value, which would re-enable the silent fallback.
    assert 'os.environ.get("DATABASE_URL"' not in text, (
        "alembic env.py must not read DATABASE_URL directly — funnel through "
        "Settings so the missing-env check is shared."
    )
