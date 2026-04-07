# T-32: cloglog agents list CLI command

*2026-04-07T15:47:57Z by Showboat 0.6.1*
<!-- showboat-id: 89b0d36e-713f-4774-a8f1-1f9cbe6e20db -->

Added `cloglog agents list` command to the CLI. Lists registered agents (worktrees) for a project with status icons, branch names, current task, and last heartbeat. Supports --json output and --status filtering.

## CLI Help Output

```bash
uv run python -c "from src.gateway.cli import app; from typer.testing import CliRunner; r = CliRunner().invoke(app, [\"agents\", \"list\", \"--help\"]); print(r.output)"
```

```output
                                                                                
 Usage: cloglog agents list [OPTIONS]                                           
                                                                                
 List registered agents (worktrees) for a project.                              
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --project        TEXT  Project name or UUID [env var: CLOGLOG_PROJECT]    │
│                           [required]                                         │
│    --url            TEXT  Base URL                                           │
│                           [env var: CLOGLOG_URL]                             │
│                           [default: http://localhost:8000]                   │
│    --status         TEXT  Filter by status                                   │
│    --json                 JSON output                                        │
│    --help                 Show this message and exit.                        │
╰──────────────────────────────────────────────────────────────────────────────╯


```

## Test Results (8 new tests)

```bash
uv run pytest tests/gateway/test_cli.py -v -k "agents" 2>&1 | grep "PASSED\|FAILED"
```

```output
tests/gateway/test_cli.py::test_agents_list_command_exists PASSED        [ 12%]
tests/gateway/test_cli.py::test_agents_list_table_output PASSED          [ 25%]
tests/gateway/test_cli.py::test_agents_list_json_output PASSED           [ 37%]
tests/gateway/test_cli.py::test_agents_list_status_filter PASSED         [ 50%]
tests/gateway/test_cli.py::test_agents_list_empty PASSED                 [ 62%]
tests/gateway/test_cli.py::test_agents_list_unknown_project PASSED       [ 75%]
tests/gateway/test_cli.py::test_agents_list_shows_heartbeat PASSED       [ 87%]
tests/gateway/test_cli.py::test_agents_list_shows_current_task PASSED    [100%]
```
