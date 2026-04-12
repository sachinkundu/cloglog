#!/bin/bash
# Block edits to .env files, credentials, secrets, and .mcp.json.
# These files contain API keys, port assignments, and infra config
# that should never be modified by agents.

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.content // empty' 2>/dev/null)

# No file path — pass through
[[ -z "$FILE_PATH" ]] && exit 0

BASENAME=$(basename "$FILE_PATH")

# Block .env files
case "$BASENAME" in
  .env|.env.local|.env.production|.env.development)
    echo "Blocked: do not edit $BASENAME — contains port assignments and API keys"
    exit 2
    ;;
esac

# Block credentials and secrets
if echo "$FILE_PATH" | grep -qiE 'credentials|secrets|\.mcp\.json'; then
  echo "Blocked: do not edit $BASENAME — contains sensitive configuration"
  exit 2
fi

exit 0
