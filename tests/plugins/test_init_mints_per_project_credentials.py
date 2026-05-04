"""Pin tests: T-398 Guard 1.

/init must always mint and write the project API key to
~/.cloglog/credentials.d/<slug> (mode 0600). It must never write the legacy
~/.cloglog/credentials global file in Phase 2.

These pins enforce:
1. Phase 2 Step 3 always writes to credentials.d/<slug>.
2. Phase 2 never writes to ~/.cloglog/credentials (the legacy global).
3. The MULTI_PROJECT conditional branch is absent — it was the source of the
   T-398 incident (antisocial session silently bound to cloglog because
   ~/.cloglog/credentials.d/antisocial was absent and the MCP server fell
   through to the legacy global file).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"


def _read() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing — fix path or file was moved"
    return INIT_SKILL.read_text(encoding="utf-8")


def _phase2_body(body: str) -> str:
    """Extract the text of Phase 2 (between ### Phase 2 and the next ## Step)."""
    lines = body.splitlines()
    in_phase2 = False
    phase2_lines: list[str] = []
    for line in lines:
        if line.startswith("### Phase 2"):
            in_phase2 = True
            phase2_lines.append(line)
            continue
        if in_phase2:
            if line.startswith("## Step "):
                break
            phase2_lines.append(line)
    assert phase2_lines, "Could not locate ### Phase 2 section in init SKILL.md"
    return "\n".join(phase2_lines)


def test_phase2_always_writes_to_credentials_d() -> None:
    """Phase 2 must write the key to credentials.d/<slug>, not the legacy global."""
    phase2 = _phase2_body(_read())
    assert "credentials.d" in phase2, (
        "Phase 2 must write to ~/.cloglog/credentials.d/<slug>. "
        "The legacy global write was removed in T-398."
    )
    assert '> "${HOME}/.cloglog/credentials.d/${PROJECT_SLUG}"' in phase2, (
        "Phase 2 Step 3 must write the key to "
        '"${HOME}/.cloglog/credentials.d/${PROJECT_SLUG}". '
        "See T-398: /init always mints per-project credentials."
    )


def test_phase2_never_writes_legacy_global_credentials() -> None:
    """Phase 2 must not write to ~/.cloglog/credentials (the legacy global).

    Writing the global file is only safe on hosts where project_id is not
    set — but /init always seeds project_id into config.yaml, so after
    bootstrap the T-398 strict-fallback guard in loadApiKey would refuse
    to read the legacy file anyway, breaking the next start.
    """
    phase2 = _phase2_body(_read())
    # No bash write to the legacy path. Comments and explanatory prose
    # mentioning the file name are permitted; what is forbidden is a
    # shell write (> ~/.cloglog/credentials or > ${HOME}/.cloglog/credentials
    # without .d/).
    bash_lines = [
        line
        for line in phase2.splitlines()
        if not line.strip().startswith("#") and not line.strip().startswith(">")
    ]
    bash_body = "\n".join(bash_lines)
    assert "> ~/.cloglog/credentials\n" not in bash_body, (
        "Phase 2 must not write to ~/.cloglog/credentials. "
        "Always write to credentials.d/<slug> (T-398 Guard 1)."
    )
    assert '> "${HOME}/.cloglog/credentials"\n' not in bash_body, (  # noqa: E501
        "Phase 2 must not write to ${HOME}/.cloglog/credentials. "
        "Always write to credentials.d/<slug> (T-398 Guard 1)."
    )


def test_phase2_no_multi_project_conditional() -> None:
    """MULTI_PROJECT conditional is absent from Phase 2.

    The MULTI_PROJECT=false/true branch was the mechanism that routed to the
    legacy global file on single-project hosts. Since T-398 we always write
    per-project credentials, so the conditional is unnecessary and must be
    removed to prevent future regressions.
    """
    phase2 = _phase2_body(_read())
    assert "MULTI_PROJECT" not in phase2, (
        "Phase 2 must not contain a MULTI_PROJECT conditional. "
        "T-398 removed the single-project shortcut that wrote to ~/.cloglog/credentials. "
        "Always write to credentials.d/<slug>."
    )


def test_phase2_writes_per_project_chmod_600() -> None:
    """The per-project credentials file must be created with mode 0600."""
    phase2 = _phase2_body(_read())
    assert "chmod 600" in phase2, "Phase 2 must chmod 600 the per-project credentials file."
    assert "mkdir -p ~/.cloglog/credentials.d" in phase2, (
        "Phase 2 must create ~/.cloglog/credentials.d/ before writing the key."
    )
