#!/bin/bash
# Install dev-clone-only git hooks.
#
# Today: pre-commit guard rejecting direct commits to `main`.
#
# Background: post-T-300 the dev clone has a writable local `main`. Any
# direct commit there leaks into worktrees branched from local `main`
# and corrupts the wt-* / PR flow. The guard makes that mistake loud.
#
# Idempotent — safe to re-run; overwrites the managed hook in place.
# Per-clone (writes .git/hooks/pre-commit, never tracked in the repo).
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "install-dev-hooks: not inside a git repository" >&2
  exit 1
fi

# Resolve the hooks directory via --git-path so worktrees get their parent
# clone's hooks dir (a worktree's .git is a file pointing at the main
# clone's git dir). On the dev clone itself this is just .git/hooks.
HOOKS_DIR="$(git -C "${REPO_ROOT}" rev-parse --git-path hooks)"
mkdir -p "${HOOKS_DIR}"

HOOK_PATH="${HOOKS_DIR}/pre-commit"

cat > "${HOOK_PATH}" <<'HOOK'
#!/bin/bash
# Reject commits directly on `main` unless ALLOW_MAIN_COMMIT=1 is set.
#
# Installed by scripts/install-dev-hooks.sh. Do not edit directly —
# re-run the installer if the guard logic needs to change.
#
# Background: dev clone has a writable local `main` (post-T-300).
# Direct main commits leak into worktrees branched from local main.
# Override (ALLOW_MAIN_COMMIT=1) is for emergency-rollback cherry-picks
# only; the standard flow is a wt-* branch + PR.
branch="$(git symbolic-ref --short HEAD 2>/dev/null || true)"
if [[ "${branch}" == "main" && "${ALLOW_MAIN_COMMIT:-}" != "1" ]]; then
  echo "ERROR: commits to main are blocked." >&2
  echo "  Use a wt-* branch + PR (the standard flow), or set" >&2
  echo "  ALLOW_MAIN_COMMIT=1 to override (rare — typically only for" >&2
  echo "  cherry-picks during emergency rollback)." >&2
  exit 1
fi
HOOK

chmod +x "${HOOK_PATH}"

echo "install-dev-hooks: installed pre-commit guard at ${HOOK_PATH}"
