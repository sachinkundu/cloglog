# Phase 2: Board Redesign & Feature Completion

**Date:** 2026-04-04
**Status:** Design approved

## Problem

The current board is flat — all tasks sit in columns as a flat list with a text breadcrumb. There's no visual hierarchy showing epics and features. The dashboard lacks real-time updates, task editing, drag-and-drop, and several features from the original design spec.

## Board Layout: Grouped Backlog + Flat Flow

### Backlog Column (left, ~280px)

A collapsible tree: Epic > Feature > Task.

- **Epic headers**: Colored left border (each epic gets a distinct auto-assigned color from a palette of 8-10). Expand/collapse triangle. Progress count showing "X/Y" (done/total tasks across all features).
- **Feature headers**: Nested under epic with indentation. Expand/collapse triangle. Progress count "X/Y".
- **Task cards**: Compact (title only) nested under features. Clickable to open detail panel.
- **Collapsed state**: Only epic header visible with progress count. One click to expand to features, another to expand to tasks.

### Flow Columns (Assigned, In Progress, Review, Done)

Flat task cards with **breadcrumb pills**:

- **Epic pill**: Saturated background using the epic's color (e.g., purple for Auth System).
- **Feature pill**: Lighter shade of the same color.
- Pills are small (10px font, rounded) and sit at the top of the card.
- Below pills: task title, then meta row (agent indicator + priority badge + document chips).

### Blocked Treatment

Tasks with `status: "blocked"` stay in their current flow column (not moved to a separate column). They get:
- Red left border on the card
- Small "blocked" badge in the meta row

### Done Column

Cards are dimmed (reduced opacity) with strikethrough title. Still show breadcrumb pills.

### Board Header

Project name + summary stats: "N tasks · N agents · X% done"

## Detail Panel

Slide-out panel from the right (~400px wide), overlays the board. Close button + click-outside-to-close.

Content adapts to what was clicked:

### Epic Detail
- Title, description, bounded context label
- Progress bar (tasks done / total across all features)
- Attached documents list — **primary location for specs, plans, designs**
- Feature list with completion counts

### Feature Detail
- Title, description
- Progress bar (tasks done / total)
- Attached documents — **where most planning artifacts live**
- Task list with status indicators
- Parent epic shown as clickable colored pill

### Task Detail
- Title, description, status, priority
- Assigned agent (worktree name) or "unassigned"
- Epic > Feature breadcrumb pills (clickable to navigate to parent detail)
- Attached documents (if any — typically fewer than feature level)
- Edit/delete actions (Interactive Board epic)

### Panel Navigation
Clicking an epic pill inside a task detail switches the panel to that epic. Clicking a feature pill switches to that feature. Breadcrumb-style navigation within the panel.

## API Changes

### New Endpoint: Backlog Tree

`GET /projects/{project_id}/backlog`

Returns:
```json
[
  {
    "epic": { "id": "uuid", "title": "Auth System", "description": "...", "color": "#7c3aed", "status": "in_progress" },
    "features": [
      {
        "feature": { "id": "uuid", "title": "OAuth Provider", "description": "...", "status": "in_progress" },
        "tasks": [
          { "id": "uuid", "title": "Add OAuth callback", "status": "backlog", "priority": "normal" }
        ],
        "task_counts": { "total": 3, "done": 1 }
      }
    ],
    "task_counts": { "total": 8, "done": 2 }
  }
]
```

### Model Change: Epic Color

New `color` column on the `epics` table (String, 7 chars for hex). Auto-assigned from a rotating palette on creation. Alembic migration required.

### Board Response Change

Add `epic_color` field to the task response in `GET /projects/{id}/board` so the frontend can render breadcrumb pills with the correct color without a separate lookup.

### New Document Endpoints

- `GET /epics/{epic_id}/documents` — documents attached to an epic
- `GET /features/{feature_id}/documents` — documents attached to a feature

(Tasks already have `GET /tasks/{task_id}/documents`.)

## Epic Hierarchy on the Board

### Epic 1: Board Redesign (Phase 2A — build first)
- **Grouped Backlog**: Backlog API, epic color model, collapsible tree component
- **Breadcrumb Pills**: Reusable pill component, integration into TaskCard
- **Multi-level Detail Panel**: Shell component, epic/feature/task views, navigation
- **Blocked Card Treatment**: Red border + badge, no separate column

### Epic 2: Live Dashboard
- **SSE Event Pipeline**: Backend emits events for task status, worktree online/offline, document attached
- **Real-time UI Updates**: Card animation, agent pulse, project stats, status indicator

### Epic 3: Interactive Board
- **Task Editing**: Edit form in detail panel, delete with confirmation, DELETE endpoint
- **Drag-and-Drop Reordering**: @dnd-kit, drag between columns (status), drag within column (position)

### Epic 4: Operations & Reliability
- **Task Assignment CLI**: tasks list, tasks assign, agents list commands
- **Heartbeat Timeout Cleanup**: Background job, mark stale sessions, emit SSE events
- **Feature Dependency Enforcement**: Block task start if upstream incomplete, visual badge

### Epic 5: Document Trail
- **Document Viewer**: Markdown rendering, document chip wiring, version history

## Phasing

**Phase 2A**: Board Redesign epic only. One spec, one wave. This is the foundation — the grouped backlog, breadcrumb pills, detail panel, and blocked treatment must be in place before the other epics make sense.

**Phase 2B**: Epics 2-5 as separate waves, each with its own DDD contract designed by the architect/reviewer agents before worktrees launch.

## Out of Scope

- Epic/feature editing from the dashboard (can be added later)
- Board filtering by epic (removed — backlog tree makes it unnecessary)
- Swimlane view (alternative approach we rejected)
- Multi-project board view (each project has its own board)
