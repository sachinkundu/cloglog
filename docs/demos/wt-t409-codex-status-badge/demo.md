# Operators can now see a discriminated codex-review badge on each Kanban task card — working / N of M / pass / exhausted / stale — instead of just a binary reviewed boolean.

*2026-05-04T07:25:46Z by Showboat 0.6.1*
<!-- showboat-id: 890bf7b9-0bb6-43f2-a950-51cb126cc84b -->

New CodexStatus enum in src/review/interfaces.py — seven states replace the old 'touched' boolean

```bash
grep -A10 "class CodexStatus" src/review/interfaces.py | grep -v "^--"
```

```output
class CodexStatus(StrEnum):
    """Discriminated codex review state for a single PR.

    Projected by ``IReviewTurnRegistry.codex_status_by_pr`` for the Board
    context. Each value maps to a distinct badge on the Kanban card so an
    operator can answer "is codex working / done / stuck" at a glance without
    grepping logs. ``NOT_STARTED`` renders no badge.
    """

    NOT_STARTED = "not_started"
    WORKING = "working"
class CodexStatusResult:
    """Combined codex status + optional progress for one PR."""

    status: CodexStatus
    progress: CodexProgress | None = None


class IReviewTurnRegistry(Protocol):
    """Persistent turn accounting for the two-stage review pipeline."""

    async def claim_turn(
```

Board API schema (src/board/schemas.py) now carries codex_status and codex_progress alongside the deprecated boolean

```bash
grep -E "codex_status|codex_progress|codex_review_picked_up" src/board/schemas.py
```

```output
    # don't break. Use codex_status for the full discriminated state.
    codex_review_picked_up: bool = False
    codex_status: CodexStatus | None = None
    codex_progress: CodexProgress | None = None
```

ReviewTurnRepository._derive_codex_status is a pure static function — no DB needed to verify all 7 states

```bash
uv run --quiet python - <<'PY'
from types import SimpleNamespace
from src.review.repository import ReviewTurnRepository

SHA = "a" * 40
NEW_SHA = "b" * 40

def turn(sha, status, consensus=False, turn_number=1):
    return SimpleNamespace(
        head_sha=sha, status=status, consensus_reached=consensus, turn_number=turn_number
    )

cases = [
    ("NOT_STARTED - no turns",    [], SHA,     1, "not_started"),
    ("NOT_STARTED - empty sha",   [], "",      1, "not_started"),
    ("WORKING     - running turn", [turn(SHA, "running")], SHA, 1, "working"),
    ("PASS        - consensus",    [turn(SHA, "completed", True)], SHA, 1, "pass"),
    ("EXHAUSTED   - 3/3 no-cons",  [turn(SHA,"completed",False,i) for i in range(1,4)], SHA, 3, "exhausted"),
    ("FAILED      - timed_out",    [turn(SHA, "timed_out")], SHA, 1, "failed"),
    ("PROGRESS    - 1/3",          [turn(SHA, "completed", False)], SHA, 3, "progress"),
    ("STALE       - new sha",      [turn(SHA, "completed", True)], NEW_SHA, 1, "stale"),
]

all_ok = True
for label, turns, sha, max_t, expected in cases:
    result = ReviewTurnRepository._derive_codex_status(turns, sha, max_t)
    ok = result.status.value == expected
    all_ok = all_ok and ok
    marker = "OK" if ok else "FAIL"
    print("  %s %s -> %s" % (marker, label, result.status.value))

suffix = "states verified OK" if all_ok else "FAILURE: some states incorrect"
print("%d %s" % (len(cases), suffix))
PY
```

```output
  OK NOT_STARTED - no turns -> not_started
  OK NOT_STARTED - empty sha -> not_started
  OK WORKING     - running turn -> working
  OK PASS        - consensus -> pass
  OK EXHAUSTED   - 3/3 no-cons -> exhausted
  OK FAILED      - timed_out -> failed
  OK PROGRESS    - 1/3 -> progress
  OK STALE       - new sha -> stale
8 states verified OK
```

Pin test: board API contract carries codex_status, codex_progress, and codex_review_picked_up on TaskCard

```bash
uv run --quiet python - <<'PY'
import ast, sys
tree = ast.parse(open("src/board/schemas.py").read())
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == "TaskCard":
        fields = []
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                name = stmt.target.id
                if name.startswith("codex"):
                    fields.append(name)
        print("TaskCard codex fields: " + ", ".join(fields))
        break
PY
```

```output
TaskCard codex fields: codex_review_picked_up, codex_status, codex_progress
```

Webhook consumer updates pr_head_sha on PR_OPENED and PR_SYNCHRONIZE so the board can project accurate status

```bash
grep -E "PR_OPENED|PR_SYNCHRONIZE|pr_head_sha" src/gateway/webhook_consumers.py | head -8
```

```output
        WebhookEventType.PR_OPENED,
        WebhookEventType.PR_SYNCHRONIZE,
            # Update pr_head_sha on the task so the board can project codex
            if event.type in (WebhookEventType.PR_OPENED, WebhookEventType.PR_SYNCHRONIZE):
                    await self._update_pr_head_sha(event.pr_url, head_sha, session)
    async def _update_pr_head_sha(self, pr_url: str, head_sha: str, session: AsyncSession) -> None:
            await repo.update_task(task.id, pr_head_sha=head_sha)
            logger.debug("Updated pr_head_sha=%s for task %s (%s)", head_sha[:7], task.id, pr_url)
```
