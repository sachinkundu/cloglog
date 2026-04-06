#!/bin/bash
# Manage isolated infrastructure for a worktree.
#
# Usage:
#   scripts/worktree-infra.sh up    # Create DB, run migrations, write .env
#   scripts/worktree-infra.sh down  # Drop DB, kill port processes, remove .env

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source port assignments
export WORKTREE_PATH="${WORKTREE_PATH:-$REPO_ROOT}"
source "$SCRIPT_DIR/worktree-ports.sh"

# PostgreSQL connection defaults (match docker-compose.yml)
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_PASSWORD="${PG_PASSWORD:-postgres}"
export PGPASSWORD="$PG_PASSWORD"

CMD="${1:-}"

case "$CMD" in
  up)
    echo "Setting up infrastructure for $(basename "$WORKTREE_PATH")..."
    echo "  Backend port: $BACKEND_PORT"
    echo "  Frontend port: $FRONTEND_PORT"
    echo "  Database: $WORKTREE_DB_NAME"

    # Create database if it doesn't exist
    if psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -tc "SELECT 1 FROM pg_database WHERE datname='$WORKTREE_DB_NAME'" 2>/dev/null | grep -q 1; then
      echo "  Database already exists"
    else
      psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -c "CREATE DATABASE $WORKTREE_DB_NAME" 2>/dev/null
      echo "  Database created"
    fi

    # Run migrations
    cd "$REPO_ROOT"
    DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head 2>&1 | tail -1
    echo "  Migrations applied"

    # Write .env file
    cat > "$WORKTREE_PATH/.env" <<EOF
BACKEND_PORT=$BACKEND_PORT
FRONTEND_PORT=$FRONTEND_PORT
DB_PORT=$DB_PORT
WORKTREE_DB_NAME=$WORKTREE_DB_NAME
DATABASE_URL=$DATABASE_URL
EOF
    echo "  .env written"
    echo "Infrastructure ready."
    ;;

  down)
    echo "Tearing down infrastructure for $(basename "$WORKTREE_PATH")..."

    # Kill processes on worktree ports
    for PORT in "$BACKEND_PORT" "$FRONTEND_PORT"; do
      if fuser "$PORT/tcp" 2>/dev/null; then
        fuser -k "$PORT/tcp" 2>/dev/null && echo "  Killed process on port $PORT" || true
      fi
    done

    # Drop the database
    if psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -tc "SELECT 1 FROM pg_database WHERE datname='$WORKTREE_DB_NAME'" 2>/dev/null | grep -q 1; then
      # Terminate active connections first
      psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$WORKTREE_DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true
      psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -c "DROP DATABASE IF EXISTS $WORKTREE_DB_NAME" 2>/dev/null
      echo "  Database dropped"
    else
      echo "  Database did not exist"
    fi

    # Remove .env
    rm -f "$WORKTREE_PATH/.env"
    echo "  .env removed"
    echo "Infrastructure torn down."
    ;;

  *)
    echo "Usage: $(basename "$0") {up|down}"
    echo ""
    echo "  up    Create worktree database, run migrations, write .env"
    echo "  down  Drop database, kill port processes, remove .env"
    exit 1
    ;;
esac
