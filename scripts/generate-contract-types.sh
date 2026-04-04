#!/bin/bash
set -euo pipefail

# Generate TypeScript types from an OpenAPI contract file.
# Usage: ./scripts/generate-contract-types.sh <contract.openapi.yaml> [output-dir]
#
# Default output: frontend/src/api/generated-types.ts

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

CONTRACT_FILE="${1:?Usage: $0 <contract.openapi.yaml> [output-dir]}"
OUTPUT_DIR="${2:-$REPO_ROOT/frontend/src/api}"
OUTPUT_FILE="$OUTPUT_DIR/generated-types.ts"

if [[ ! -f "$CONTRACT_FILE" ]]; then
  echo "Error: Contract file not found: $CONTRACT_FILE"
  exit 1
fi

echo "Generating TypeScript types from: $CONTRACT_FILE"
echo "Output: $OUTPUT_FILE"

cd "$REPO_ROOT/frontend"
npx openapi-typescript "$CONTRACT_FILE" -o "$OUTPUT_FILE"

echo "Generated: $OUTPUT_FILE"
