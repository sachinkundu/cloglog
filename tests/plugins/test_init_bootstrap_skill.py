"""Pin tests: T-320.

init Step 2 must bootstrap a fresh project via a direct HTTP call to the backend,
not via mcp__cloglog__get_board (which cannot run before MCP is configured).

These tests assert:
1. Absence of mcp__cloglog__get_board in Step 2 (old broken path).
2. Presence of the curl-based project creation call in Step 2.
3. Presence of credential-writing steps (credentials file + project_id).
4. Presence of the restart instruction (two-phase protocol).
5. Default backend URL is http://localhost:8001, not http://localhost:8000.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INIT_SKILL = REPO_ROOT / "plugins/cloglog/skills/init/SKILL.md"


def _read() -> str:
    assert INIT_SKILL.exists(), f"{INIT_SKILL} missing — fix path or file was moved"
    return INIT_SKILL.read_text(encoding="utf-8")


def _step2_body(body: str) -> str:
    """Extract the text of Step 2 (between ## Step 2 and the next ## Step)."""
    lines = body.splitlines()
    in_step2 = False
    step2_lines: list[str] = []
    for line in lines:
        if line.startswith("## Step 2"):
            in_step2 = True
            step2_lines.append(line)
            continue
        if in_step2:
            if line.startswith("## Step ") and not line.startswith("## Step 2"):
                break
            step2_lines.append(line)
    assert step2_lines, "Could not locate ## Step 2 section in init SKILL.md"
    return "\n".join(step2_lines)


# ---------------------------------------------------------------------------
# Absence pins — old broken path must not return
# ---------------------------------------------------------------------------


def test_step2_does_not_call_mcp_get_board() -> None:
    """mcp__cloglog__get_board must not appear in Step 2.

    On a fresh project the MCP server is not yet configured, so this call
    would fail before any credentials are written.
    """
    step2 = _step2_body(_read())
    assert "mcp__cloglog__get_board" not in step2, (
        "Step 2 must not call mcp__cloglog__get_board — the MCP server is not "
        "configured on a fresh project. Use the direct HTTP bootstrap path instead."
    )


def test_skill_uses_127_0_0_1_not_localhost_as_default() -> None:
    """Default backend URL must use 127.0.0.1, not localhost.

    On IPv6-first hosts, 'localhost' resolves to '::1' and the Node MCP server
    fails with ECONNREFUSED (fixed in T-247, documented in
    docs/demos/wt-fix-localhost/demo.md). Port 8000 is also forbidden as a default
    (reserved for cloglog's own dev server).
    """
    body = _read()
    step2 = _step2_body(body)
    # Step 2 default must use 127.0.0.1:8001
    assert "127.0.0.1:8001" in step2, (
        "Step 2 default BACKEND_URL must be http://127.0.0.1:8001, not localhost:8001. "
        "On IPv6-first hosts localhost resolves to ::1 and the MCP server fails."
    )
    # Forbid localhost in Step 2 default (comments explaining the fix are fine)
    for line in step2.splitlines():
        stripped = line.strip()
        if "localhost:8001" in stripped:
            assert stripped.startswith("#") or stripped.startswith(">"), (
                f"Step 2 references localhost:8001 outside a comment/note:\n"
                f"  {line!r}\n"
                "Use 127.0.0.1:8001 to avoid IPv6 resolution failures."
            )
    # Port :8000 must not appear as a bare default anywhere in the skill
    for line in body.splitlines():
        stripped = line.strip()
        if "localhost:8000" in stripped or "127.0.0.1:8000" in stripped:
            assert stripped.startswith("#") or stripped.startswith(">"), (
                f"init SKILL.md references :8000 outside a comment/note:\n"
                f"  {line!r}\n"
                "Port 8000 is cloglog's own dev server only."
            )


# ---------------------------------------------------------------------------
# Presence pins — new bootstrap path must exist in Step 2
# ---------------------------------------------------------------------------


def test_step2_uses_curl_to_create_project() -> None:
    """Step 2 must call the backend via curl to create the project."""
    step2 = _step2_body(_read())
    assert "curl" in step2, (
        "Step 2 must create the project via a direct curl call to "
        "POST /api/v1/board/projects — not via MCP tools."
    )


def test_step2_posts_to_projects_endpoint() -> None:
    """Step 2 must POST to /api/v1/projects (not /api/v1/board/projects).

    The board router mounts at /api/v1 with no additional prefix, so
    @router.post('/projects') maps to /api/v1/projects.
    """
    step2 = _step2_body(_read())
    assert "/api/v1/projects" in step2, (
        "Step 2 must POST to /api/v1/projects to create the project "
        "without requiring pre-existing MCP credentials."
    )
    assert "/api/v1/board/projects" not in step2, (
        "Step 2 must NOT reference /api/v1/board/projects — that path does not exist "
        "(the board router mounts at /api/v1 with no extra prefix)."
    )


def test_step2_uses_dashboard_key_auth() -> None:
    """Step 2 must authenticate using the X-Dashboard-Key header with DASHBOARD_SECRET."""
    step2 = _step2_body(_read())
    assert "X-Dashboard-Key" in step2, (
        "Step 2 must pass the dashboard key via -H 'X-Dashboard-Key: ...' "
        "so the operator can bootstrap without an existing project API key."
    )
    assert "DASHBOARD_SECRET" in step2, (
        "Step 2 must read the key from $DASHBOARD_SECRET (the env var the backend "
        "validates against, per src/shared/config.py). Not CLOGLOG_DASHBOARD_KEY."
    )


def test_step2_writes_credentials_file() -> None:
    """Step 2 must write ~/.cloglog/credentials with the new API key."""
    step2 = _step2_body(_read())
    assert "~/.cloglog/credentials" in step2, (
        "Step 2 must write the project API key to ~/.cloglog/credentials "
        "so the MCP server can load it on restart."
    )


def test_step2_writes_project_id_to_config() -> None:
    """Step 2 must persist the project_id to .cloglog/config.yaml."""
    step2 = _step2_body(_read())
    assert "project_id" in step2, (
        "Step 2 must write project_id to .cloglog/config.yaml "
        "so subsequent init re-runs detect the existing project."
    )


def test_step2_requests_restart() -> None:
    """Step 2 must instruct the operator to restart Claude Code after Phase 2."""
    step2 = _step2_body(_read())
    restart_mentioned = "restart" in step2.lower()
    assert restart_mentioned, (
        "Step 2 must tell the operator to restart Claude Code after writing "
        "credentials — the MCP server reads the API key only at startup."
    )


def test_step2_checks_credentials_alongside_project_id() -> None:
    """Phase 1 must verify BOTH project_id AND credentials before skipping to Step 3.

    A repo with .cloglog/config.yaml checked in (project_id present) but no
    ~/.cloglog/credentials on a fresh machine must NOT skip Phase 2 — the MCP
    server hard-exits at startup without the API key (mcp-server/src/credentials.ts).
    """
    step2 = _step2_body(_read())
    # Both conditions must be mentioned
    assert "CLOGLOG_API_KEY" in step2 or "credentials" in step2.lower(), (
        "Step 2 Phase 1 must check for credentials (CLOGLOG_API_KEY or "
        "~/.cloglog/credentials) in addition to project_id, so a cloned repo "
        "with no local credentials gets the repair path, not a broken MCP startup."
    )


def test_step2_detects_existing_project_id_not_credentials() -> None:
    """Step 2 must use repo-local project_id as the skip condition, not ~/.cloglog/credentials.

    ~/.cloglog/credentials is global (shared across all projects on the machine).
    Using it as a skip condition would cause a machine with credentials for project A
    to silently skip Phase 2 when initializing project B, reusing A's key.

    The canonical "already bootstrapped" signal is project_id in .cloglog/config.yaml,
    which is repo-scoped.
    """
    step2 = _step2_body(_read())
    assert "project_id" in step2, (
        "Step 2 must check for project_id in .cloglog/config.yaml as the "
        "repo-scoped 'already bootstrapped' signal. ~/.cloglog/credentials is "
        "a global file and must not be used as the skip condition."
    )


# ---------------------------------------------------------------------------
# T-316 — Step 4a must emit every config key the consumers depend on
# ---------------------------------------------------------------------------


def _step4a_body(body: str) -> str:
    """Extract Step 4a (the config.yaml subsection)."""
    lines = body.splitlines()
    in_step4a = False
    out: list[str] = []
    for line in lines:
        if line.startswith("### 4a."):
            in_step4a = True
            out.append(line)
            continue
        if in_step4a:
            if line.startswith("### ") and not line.startswith("### 4a."):
                break
            out.append(line)
    assert out, "Could not locate ### 4a. section in init SKILL.md"
    return "\n".join(out)


def test_step4a_documents_t316_config_keys() -> None:
    """Step 4a must document every key T-316 consumers expect.

    Without these keys ``scripts/check-demo.sh`` errors with
    ``demo_allowlist_paths missing or empty`` and the auto-merge gate
    matches no reviewer (``not_codex_reviewer`` for every event), so a
    downstream project initialized exactly per this skill is broken
    out of the box. The pin scopes to Step 4a so a future rewording
    that drops a key from the example config trips the test.
    """
    step4a = _step4a_body(_read())
    for key in (
        "dashboard_key",
        "webhook_tunnel_name",
        "reviewer_bot_logins",
        "demo_allowlist_paths",
    ):
        assert key in step4a, (
            f"init Step 4a must include the {key!r} key in its example config — "
            "T-316 consumers fail closed without it."
        )


# ---------------------------------------------------------------------------
# T-382 — per-project credential resolution must propagate to init
# ---------------------------------------------------------------------------


def test_step2_always_writes_credentials_d() -> None:
    """T-398: Step 2 must always write to ~/.cloglog/credentials.d/<slug>.

    T-382 introduced per-project credentials but kept a MULTI_PROJECT branch
    that wrote to the legacy ~/.cloglog/credentials on single-project hosts.
    T-398 removed that branch: /init now always writes the per-project file
    because project_id is always set in config.yaml after bootstrap, and the
    T-398 strict-fallback guard refuses the legacy file when project_id is
    present — so writing there would break the next start.
    """
    step2 = _step2_body(_read())
    assert "credentials.d" in step2, (
        "Step 2 must write to ~/.cloglog/credentials.d/<slug> (T-382/T-398). "
        "Per-project credential files are always used since T-398."
    )
    assert "MULTI_PROJECT" not in step2, (
        "Step 2 must not contain a MULTI_PROJECT conditional (T-398). "
        "The single-project shortcut that wrote to ~/.cloglog/credentials was "
        "removed because project_id is always set after bootstrap and the "
        "T-398 strict-fallback guard refuses the legacy file when project_id is set."
    )


def test_step2_seeds_project_slug_into_config() -> None:
    """T-382: Step 2 must persist `project:` to .cloglog/config.yaml at
    bootstrap time. Without it, the SessionEnd unregister hook and the
    MCP server resolver fall back to basename($PROJECT_ROOT) for the slug
    — which matches the credentials.d/<slug> file only by accident if the
    checkout dir happens to share the project's chosen name.
    """
    step2 = _step2_body(_read())
    # Step 2 derives PROJECT_SLUG and writes it as the `project:` field.
    assert "PROJECT_SLUG" in step2, (
        "Step 2 must derive PROJECT_SLUG so the same slug is used for both "
        "the credentials.d/<slug> filename and the config `project:` field."
    )
    # The skill's seeding block must include `project:` (not only `project_id:`).
    assert (
        "^project:" in step2 or "'project: %s\\n'" in step2 or "project: ${PROJECT_SLUG}" in step2
    ), (
        "Step 2 must persist `project:` to .cloglog/config.yaml so the "
        "T-382 resolver finds the slug source on first restart."
    )


def test_step4a_uses_project_field_not_project_name() -> None:
    """T-382: Step 4a's example config MUST use `project:` (the slug field
    the resolver reads) and MUST NOT use `project_name:` (the legacy field
    that nothing reads). A downstream project generated from `project_name:`
    has no slug source — the resolver falls back to basename which usually
    misses, breaking per-project credential lookup.
    """
    step4a = _step4a_body(_read())
    assert "\nproject:" in step4a or "project: <slug>" in step4a, (
        "Step 4a must emit the `project:` field — it's the slug source for "
        "~/.cloglog/credentials.d/<slug> (T-382)."
    )
    # The legacy `project_name:` field is not read by anything; if init
    # generates it, the per-project resolver silently fails over to basename.
    # Allow `project_name` only inside fenced comments / explanatory prose.
    for line in step4a.splitlines():
        stripped = line.strip()
        if stripped.startswith("project_name:"):
            raise AssertionError(
                "Step 4a still emits the legacy `project_name:` field. "
                "Use `project:` — that's what mcp-server/src/credentials.ts "
                "and the SessionEnd unregister hook read."
            )


def test_step2_repair_always_writes_credentials_d() -> None:
    """T-398: the Step 2 repair text (shown when project_id is in the repo
    but no credentials are on the host) must instruct the operator to always
    write to ~/.cloglog/credentials.d/<slug>.

    The T-382 repair had a conditional that wrote to ~/.cloglog/credentials
    on single-project hosts. T-398 removes that branch: since project_id is
    set in config.yaml on any bootstrapped checkout, the T-398 strict-fallback
    guard refuses the legacy file when project_id is present — so writing
    there would produce credentials the MCP server can no longer load.
    """
    body = _read()
    # Locate the repair-text block (between "Credentials missing for an
    # existing project." and the next "### " heading).
    start = body.find("Credentials missing for an existing project.")
    assert start != -1, "Repair text block not found"
    end = body.find("### ", start)
    assert end != -1, "Could not locate end of repair text block"
    repair = body[start:end]

    assert "credentials.d" in repair, (
        "Step 2 repair text must reference ~/.cloglog/credentials.d/<slug> so "
        "operators write the recovered key to the per-project file (T-382/T-398)."
    )
    # The multi-project conditional must be absent — always use credentials.d.
    assert "if [ -f ~/.cloglog/credentials ]" not in repair, (
        "Step 2 repair text must not check for ~/.cloglog/credentials and branch "
        "on it (T-398). Since project_id is set on all bootstrapped checkouts, the "
        "T-398 strict-fallback guard refuses the legacy file — writing there would "
        "break the next start. Always write to credentials.d/<slug>."
    )


def test_step2_guards_against_empty_project_slug() -> None:
    """T-382 codex round 3: PROJECT_SLUG derivation can produce empty
    string for a backend project name like '!!!' or '***'. Init must
    detect the empty case and either fall back to a validated basename
    or halt with a clear message — silently writing
    `~/.cloglog/credentials.d/` (the directory itself) is the failure
    mode this guards against.
    """
    step2 = _step2_body(_read())
    # Look for an empty-slug guard near the PROJECT_SLUG derivation.
    assert 'if [ -z "$PROJECT_SLUG" ]' in step2 or 'if [ -z "${PROJECT_SLUG}" ]' in step2, (
        "Step 2 must guard against an empty PROJECT_SLUG after the tr/sed "
        "derivation — backend names like '!!!' produce empty slugs that would "
        "write CLOGLOG_API_KEY to a directory path."
    )
    # The guard must include a fallback or a fatal exit; either keyword is fine.
    assert "exit 1" in step2 or "basename" in step2, (
        "Step 2's empty-slug guard must either fall back to a validated "
        "basename or exit 1 with a clear message — silent continuation writes "
        "the key to ~/.cloglog/credentials.d/ (the directory itself)."
    )


def test_step2_validates_existing_slug_against_path_traversal() -> None:
    """T-382 codex round 5: Step 2's Phase-1 EXISTING_SLUG derivation must
    validate the `project:` value against [A-Za-z0-9._-]+ before splicing
    it into ~/.cloglog/credentials.d/${EXISTING_SLUG}. Without the check,
    a repo that carries `project: ../escape` would probe
    ~/.cloglog/credentials.d/../escape and incorrectly report
    EXISTING_CREDS=per-project against a file outside credentials.d/.

    The runtime resolvers reject the same shape (mcp-server/src/credentials.ts
    SLUG_RE + plugins/cloglog/hooks/lib/resolve-api-key.sh resolve_api_key_slug),
    so init must follow suit or the bootstrap detection diverges from what
    the live system can actually use.
    """
    step2 = _step2_body(_read())
    # The validation regex must be present where EXISTING_SLUG is derived.
    assert "[A-Za-z0-9._-]+" in step2, (
        "Step 2 must validate the project: scalar against [A-Za-z0-9._-]+ "
        "before reading or writing ~/.cloglog/credentials.d/<slug> — "
        "unvalidated splicing allows `project: ../escape` traversal."
    )


def test_phase1_legacy_file_not_counted_when_project_id_set() -> None:
    """T-398: Phase 1 must NOT count ~/.cloglog/credentials as valid when
    project_id is set in config.yaml.

    When project_id IS set, loadApiKey's strict-fallback guard refuses the
    legacy global file and fails at MCP startup. Phase 1 treating the legacy
    file as "bootstrapped" would cause the operator to skip Phase 2 and end
    up with a non-starting MCP server.

    The fix: the elif that sets EXISTING_CREDS="file" must be guarded by
    [ -z "$EXISTING_PROJECT_ID" ] so it only fires on legacy single-project
    hosts where project_id is absent.
    """
    step2 = _step2_body(_read())
    # Verify the legacy-file elif is guarded by EXISTING_PROJECT_ID being empty.
    assert "EXISTING_PROJECT_ID" in step2 and (
        '[ -z "$EXISTING_PROJECT_ID" ]' in step2 or '[ -z "$EXISTING_PROJECT_ID" ]' in step2
    ), (
        'Phase 1 must guard the EXISTING_CREDS="file" branch with '
        '[ -z "$EXISTING_PROJECT_ID" ]. Without the guard, an existing checkout '
        "with project_id set and only a legacy global file is incorrectly reported "
        "as bootstrapped — the MCP server then fails at startup (T-398 Guard 3)."
    )


def test_step2_repair_branch_validates_slug_against_path_traversal() -> None:
    """The Step 2 repair text (multi-project branch) MUST also validate the
    derived SLUG before writing the recovered key into
    ~/.cloglog/credentials.d/${SLUG}. Same reasoning as the Phase-1 check
    above — a hostile or accidentally invalid `project:` field would
    otherwise let the operator write the recovered key outside
    credentials.d/.
    """
    body = _read()
    start = body.find("Credentials missing for an existing project.")
    end = body.find("### ", start)
    assert start != -1 and end != -1, "Repair text block not found"
    repair = body[start:end]

    assert "[A-Za-z0-9._-]+" in repair, (
        "Step 2 repair text must validate SLUG against [A-Za-z0-9._-]+ "
        "before writing ~/.cloglog/credentials.d/<slug> — unvalidated "
        "splicing allows path traversal in the recovered-key write."
    )
