---
verdict: no_demo
diff_hash: 00c4b11be0783911d1667d1203804a75dfd82e2d4b2638f8031558e126af396a
classifier: demo-classifier
generated_at: 2026-05-04T13:06:46Z
---

## Why no demo

The diff introduces a new `BoardService.create_task` method that wraps `_repo.create_task` with rollup recomputation and optional SSE event publication, then redirects three existing call sites to go through the new service method. The HTTP route decorator is unchanged (same path, same request body schema, same response shape); only the internal delegation target shifts from repo to service. The SSE event emitted (`TASK_STATUS_CHANGED`) was already part of the existing event bus protocol and is not a new observable channel.

## Changed files

- src/board/routes.py
- src/board/services.py
- tests/board/test_services.py
