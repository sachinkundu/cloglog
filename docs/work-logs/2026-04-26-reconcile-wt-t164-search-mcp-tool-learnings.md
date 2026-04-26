# Learnings — wt-t164-search-mcp-tool

Durable, non-obvious gotchas surfaced during this task.

## Demo proofs that compare across languages need the language's actual
## interpolation syntax, not a generic shape.

The Proof 2 grep that pins URL parity between `src/gateway/cli.py` and
`mcp-server/src/tools.ts` initially looked for `/projects/$project_id/`
in the CLI. That is TypeScript template-literal syntax; Python f-strings
write `/projects/{project_id}/`. The grep matched in the .ts file and
silently failed in the .py file — `cli_uses_same_endpoint=FAIL` on the
first run even though the URLs were identical. Fix: use each language's
own interpolation token in cross-language path-equivalence pins.

## `tsx` heredocs lose the script body when invoked with `<<TS` from a
## Showboat `exec` block that already nested the heredoc inside the
## bash invocation.

Tried to prove the URL shape by spawning `tsx` with a stdin heredoc that
imported `./src/tools.ts`, mocked the client, and printed the captured
URLs. Output came back as `plain=undefined / freetext=undefined /
filtered=undefined` — the calls array was empty because the handler
body never ran (likely the heredoc didn't reach tsx through the layer
of `bash -c` Showboat wraps `exec` in). Pivot: when you already have
vitest cases pinning the same contract, run those filtered (`vitest
run -t search`) instead of building a parallel proof harness; the
captured `Tests N passed` line is shorter, deterministic, and
actually exercises the production code path.

## URLSearchParams matches FastAPI's `list[str] | None` parser only
## when each value is appended individually.

For multi-valued query parameters (`status_filter=backlog` AND
`status_filter=in_progress`) the wrapper must call `params.append`
once per value — `params.set` would overwrite. The corresponding
backend route `src/board/routes.py:495` uses
`Annotated[list[str] | None, Query()]`, which only assembles a list
when the same key appears multiple times. Pinned in the
`limit + multi status_filter` vitest case so a future drift to
`set(...)` would fail loudly.
