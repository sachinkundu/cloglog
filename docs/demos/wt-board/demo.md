# Demo: T-117 Auto-Attach Documents + T-152 PR Merge Status

## T-117: Auto-attach document when spec/plan task moves to review

### Setup

Created project, epic, feature, and spec task (task_type: "spec").

### Move spec to review with pr_url — document auto-created

    PATCH /api/v1/tasks/{sid} {"status":"in_progress"}
    → {"status":"in_progress","pr_url":null,"pr_merged":false}

    PATCH /api/v1/tasks/{sid} {"status":"review","pr_url":"https://github.com/org/repo/pull/42"}
    → {"status":"review","pr_url":"https://github.com/org/repo/pull/42","pr_merged":false}

### Verify document was auto-attached to the parent feature

    GET /api/v1/documents?attached_to_type=feature&attached_to_id={fid}
    → [{
        "title": "Spec — Write design spec",
        "doc_type": "design_spec",
        "source_path": "https://github.com/org/repo/pull/42",
        "attached_to_type": "feature"
      }]

### Deduplication: moving to review again with same pr_url does NOT create duplicate

    PATCH → in_progress → review (same pr_url)
    GET documents → length: 1 (no duplicate created)

## T-152: PR Merge Status Field

### New pr_merged field in task responses (default: false)

    POST /api/v1/projects/{pid}/features/{fid}/tasks {"title":"Task","task_type":"spec"}
    → {"pr_url":null,"pr_merged":false, ...}

### Set pr_merged via PATCH

    PATCH /api/v1/tasks/{sid} {"pr_merged":true}
    → {"status":"review","pr_url":"https://github.com/org/repo/pull/42","pr_merged":true}

### Board endpoint includes pr_merged in task cards

    GET /api/v1/projects/{pid}/board
    → columns[].tasks[] includes {"pr_merged": true}

### Active tasks endpoint includes pr_merged

    GET /api/v1/projects/{pid}/active-tasks
    → [{"title":"Write design spec","pr_url":"...","pr_merged":true}]

## Test Results

101 board tests pass (91 existing + 10 new):

    tests/board/test_services.py — 4 new: auto-attach spec, plan, skip impl, dedup
    tests/board/test_routes.py — 6 new: route-level auto-attach, impl skip, pr_merged CRUD, board, active-tasks
