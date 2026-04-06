#!/bin/bash
# Orchestrates the proof-of-work demo workflow.
# Called by `make demo`.
#
# 1. Detects feature name
# 2. Sets up isolated infrastructure
# 3. Starts servers
# 4. Runs the feature's demo-script.sh
# 5. Cleans up servers (but not infrastructure — that persists for the worktree)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- Feature detection ---
FEATURE="${DEMO_FEATURE:-}"
if [[ -z "$FEATURE" ]]; then
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
  case "$BRANCH" in
    f[0-9]*-*)
      FEATURE=$(echo "$BRANCH" | grep -oP '^f\d+' || echo "")
      ;;
  esac
fi

if [[ -z "$FEATURE" ]]; then
  echo "ERROR: Cannot detect feature. Set DEMO_FEATURE env var or use f<N>-* branch naming."
  exit 1
fi

# Find the demo directory
DEMO_DIR=""
for dir in docs/demos/*/; do
  [[ -d "$dir" ]] || continue
  if echo "$dir" | grep -qi "$FEATURE"; then
    DEMO_DIR="$dir"
    break
  fi
done

DEMO_SCRIPT="${DEMO_DIR}demo-script.sh"
if [[ ! -f "$DEMO_SCRIPT" ]]; then
  echo "ERROR: No demo script found at $DEMO_SCRIPT"
  echo "Create docs/demos/<feature-name>/demo-script.sh first."
  exit 1
fi

echo "=== Proof-of-Work Demo: $FEATURE ==="
echo ""

# --- Infrastructure ---
export WORKTREE_PATH="$REPO_ROOT"
source "$SCRIPT_DIR/worktree-ports.sh"

echo "Ports: backend=$BACKEND_PORT, frontend=$FRONTEND_PORT"
echo "Database: $WORKTREE_DB_NAME"
echo ""

# Ensure DB exists and migrations are current
"$SCRIPT_DIR/worktree-infra.sh" up
echo ""

# --- Determine if frontend is needed ---
NEEDS_FRONTEND=false
if grep -q "rodney\|FRONTEND_PORT" "$DEMO_SCRIPT" 2>/dev/null; then
  NEEDS_FRONTEND=true
fi

# --- Start servers ---
PIDS=()

cleanup() {
  echo ""
  echo "Cleaning up..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null && echo "  Stopped PID $pid" || true
  done
  # Also kill by port in case PIDs changed
  fuser -k "$BACKEND_PORT/tcp" 2>/dev/null || true
  if [[ "$NEEDS_FRONTEND" == true ]]; then
    fuser -k "$FRONTEND_PORT/tcp" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "Starting backend on port $BACKEND_PORT..."
DATABASE_URL="$DATABASE_URL" uv run uvicorn src.gateway.app:create_app \
  --factory --host 0.0.0.0 --port "$BACKEND_PORT" \
  --log-level warning &
PIDS+=($!)

if [[ "$NEEDS_FRONTEND" == true ]]; then
  echo "Starting frontend on port $FRONTEND_PORT..."
  (cd frontend && VITE_BACKEND_PORT="$BACKEND_PORT" PORT="$FRONTEND_PORT" npm run dev -- --port "$FRONTEND_PORT") &
  PIDS+=($!)
fi

# --- Health check ---
echo "Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
    echo "  Backend ready."
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "ERROR: Backend failed to start within 30s"
    exit 1
  fi
  sleep 1
done

if [[ "$NEEDS_FRONTEND" == true ]]; then
  echo "Waiting for frontend..."
  for i in $(seq 1 30); do
    if curl -sf "http://localhost:$FRONTEND_PORT" >/dev/null 2>&1; then
      echo "  Frontend ready."
      break
    fi
    if [[ $i -eq 30 ]]; then
      echo "ERROR: Frontend failed to start within 30s"
      exit 1
    fi
    sleep 1
  done
fi

# --- Run demo script ---
echo ""
echo "=== Running demo script ==="
echo ""
chmod +x "$DEMO_SCRIPT"
if bash "$DEMO_SCRIPT"; then
  echo ""
  echo "=== Demo completed successfully ==="
  exit 0
else
  echo ""
  echo "=== Demo FAILED ==="
  exit 1
fi
