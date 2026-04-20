# Operators can now run cloglog agents in worktrees without the project API key being readable inside the worktree.

*2026-04-20T11:30:23Z by Showboat 0.6.1*
<!-- showboat-id: 3b427147-771c-435c-b9bf-ed5dcb530d88 -->

Before T-214, .mcp.json carried CLOGLOG_API_KEY in plaintext under mcpServers.cloglog.env. Any process inside the worktree could read it and authenticate to the backend with curl, bypassing the 'agents talk to the backend only via MCP' rule.

After T-214, the env block contains only CLOGLOG_URL. There is no project credential anywhere in the worktree.

```bash
jq ".mcpServers.cloglog.env" .mcp.json
```

```output
{
  "CLOGLOG_URL": "http://127.0.0.1:8001"
}
```

```bash
jq -r ".mcpServers.cloglog.env | keys[]" .mcp.json | sort
```

```output
CLOGLOG_URL
```

The MCP server reads CLOGLOG_API_KEY from the operator environment first, then from ~/.cloglog/credentials (mode 0600). The path is in the operator's home directory; agent-vm sandboxes never see it.

```bash
stat -c "%a" "$HOME/.cloglog/credentials"
```

```output
600
```

```bash
grep -c "^CLOGLOG_API_KEY=" "$HOME/.cloglog/credentials"
```

```output
1
```

Positive path: the MCP server resolves the key (env or credentials file), connects its stdio transport, and prints its ready line. Stdin from /dev/null closes the transport, so the process exits cleanly with status 0.

```bash
timeout 3 node mcp-server/dist/index.js < /dev/null 2>&1 | head -1; echo "exit=${PIPESTATUS[0]}"
```

```output
cloglog-mcp: server started on stdio
exit=0
```

Negative path: with HOME pointed at a nonexistent directory and CLOGLOG_API_KEY unset, the MCP server prints an actionable diagnostic to stderr and exits with EX_CONFIG (78). Claude Code's MCP loader will surface this as a failed server — agents inside the worktree see no mcp__cloglog__* tools, so they cannot proceed without the operator fixing the credentials.

```bash
HOME=/nonexistent env -u CLOGLOG_API_KEY node mcp-server/dist/index.js < /dev/null > /tmp/t214-neg.out 2>&1; ec=$?; cat /tmp/t214-neg.out; echo "exit=$ec"
```

```output
cloglog-mcp: CLOGLOG_API_KEY is not set and no usable credentials file was found at /nonexistent/.cloglog/credentials.

Fix this by either:
  1) Exporting CLOGLOG_API_KEY in the shell that launches the MCP server, OR
  2) Creating /nonexistent/.cloglog/credentials with the project key:
       mkdir -p ~/.cloglog
       printf "CLOGLOG_API_KEY=<your-project-key>\n" > ~/.cloglog/credentials
       chmod 600 ~/.cloglog/credentials

See docs/setup-credentials.md.
exit=78
```

A pytest regression guard (tests/test_mcp_json_no_secret.py) fails fast if anyone re-adds CLOGLOG_API_KEY (or a 64-hex token) to .mcp.json. It runs as part of make quality.

```bash
uv run pytest tests/test_mcp_json_no_secret.py -q 2>&1 | grep -oE "[0-9]+ passed" | head -1
```

```output
3 passed
```
