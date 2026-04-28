#!/bin/bash
# Preflight checks for `make dev`.
# Exits non-zero with clear copy-pasteable fix commands if anything is missing or not running.

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ERRORS=()
WARNINGS=()

ok()   { echo -e "  ${GREEN}✓${NC}  $1"; }
fail() { ERRORS+=("$1"); }
warn() { WARNINGS+=("$1"); }

echo "Preflight checks..."

# ── Required binaries ────────────────────────────────────────────────────────

command -v uv >/dev/null 2>&1 \
  && ok "uv" \
  || fail "uv not found
    $(echo -e "${DIM}curl -LsSf https://astral.sh/uv/install.sh | sh${NC}")"

command -v docker >/dev/null 2>&1 \
  && ok "docker" \
  || fail "docker not found
    $(echo -e "${DIM}# Install Docker Engine:${NC}")
    $(echo -e "${DIM}curl -fsSL https://get.docker.com | sh${NC}")"

command -v node >/dev/null 2>&1 \
  && ok "node" \
  || fail "node not found
    $(echo -e "${DIM}# Install via nvm:${NC}")
    $(echo -e "${DIM}curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash${NC}")
    $(echo -e "${DIM}nvm install --lts${NC}")"

command -v npm >/dev/null 2>&1 \
  && ok "npm" \
  || fail "npm not found — reinstall node via nvm (npm is bundled with node)"

command -v jq >/dev/null 2>&1 \
  && ok "jq" \
  || fail "jq not found
    $(echo -e "${DIM}sudo apt install jq${NC}")"

command -v cloudflared >/dev/null 2>&1 \
  && ok "cloudflared" \
  || fail "cloudflared not found
    $(echo -e "${DIM}# Download and install:${NC}")
    $(echo -e "${DIM}curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared${NC}")
    $(echo -e "${DIM}chmod +x /usr/local/bin/cloudflared${NC}")"

# ── Docker daemon ────────────────────────────────────────────────────────────

if docker info >/dev/null 2>&1; then
  ok "Docker daemon running"
else
  fail "Docker daemon not running
    $(echo -e "${DIM}sudo systemctl start docker${NC}")"
fi

# ── cloudflared tunnel ───────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Read tunnel name from .cloglog/config.yaml so non-cloglog projects can ship
# their own value without forking this script (T-316). Use the canonical
# stdlib-only scalar reader so a missing key returns "" cleanly instead of
# tripping `set -e` via grep's exit-1 (codex round 1 finding).
# shellcheck source=../plugins/cloglog/hooks/lib/parse-yaml-scalar.sh
source "$REPO_ROOT/plugins/cloglog/hooks/lib/parse-yaml-scalar.sh"
TUNNEL_NAME=$(read_yaml_scalar "$REPO_ROOT/.cloglog/config.yaml" "webhook_tunnel_name" "")

if pgrep -x cloudflared >/dev/null 2>&1; then
  ok "cloudflared tunnel running"
else
  if [[ -n "$TUNNEL_NAME" ]]; then
    fail "cloudflared tunnel not running — GitHub webhooks won't reach the app
    $(echo -e "${DIM}cloudflared tunnel run ${TUNNEL_NAME}${NC}")"
  else
    fail "cloudflared tunnel not running — GitHub webhooks won't reach the app
    $(echo -e "${DIM}set webhook_tunnel_name in .cloglog/config.yaml, then: cloudflared tunnel run \$webhook_tunnel_name${NC}")"
  fi
fi

# ── Frontend node_modules ────────────────────────────────────────────────────

if [ -d "$REPO_ROOT/frontend/node_modules" ]; then
  ok "frontend/node_modules present"
else
  fail "frontend/node_modules missing
    $(echo -e "${DIM}cd frontend && npm install${NC}")"
fi

# ── GitHub App credentials ───────────────────────────────────────────────────

if [ -f "$HOME/.agent-vm/credentials/github-app.pem" ]; then
  ok "GitHub App PEM key present"
else
  warn "~/.agent-vm/credentials/github-app.pem missing — bot PR creation won't work
    Copy the PEM key from your GitHub App settings to ~/.agent-vm/credentials/github-app.pem"
fi

if [ -n "${GH_APP_ID:-}" ] && [ -n "${GH_APP_INSTALLATION_ID:-}" ]; then
  ok "GH_APP_ID and GH_APP_INSTALLATION_ID exported"
else
  warn "GH_APP_ID and/or GH_APP_INSTALLATION_ID not exported — agents calling
    plugins/cloglog/scripts/gh-app-token.py will fail with 'env var required'.
    Add to ~/.bashrc or ~/.zshenv:
    $(echo -e "${DIM}export GH_APP_ID=3235173${NC}")
    $(echo -e "${DIM}export GH_APP_INSTALLATION_ID=120404294${NC}")
    (cloglog's App and Installation IDs — not secrets, public GitHub App identifiers)"
fi

# ── Report ───────────────────────────────────────────────────────────────────

echo ""

if [ ${#WARNINGS[@]} -gt 0 ]; then
  for w in "${WARNINGS[@]}"; do
    echo -e "  ${YELLOW}⚠${NC}  $w"
  done
  echo ""
fi

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo -e "${RED}${BOLD}Preflight failed. Fix each item below, then re-run make dev:${NC}"
  echo ""
  for e in "${ERRORS[@]}"; do
    echo -e "  ${RED}✗${NC}  $e"
    echo ""
  done
  exit 1
fi

echo -e "${GREEN}All checks passed.${NC}"
