# T-134 Demo: Collapse/Expand All Toggle

## What Changed

Added a toolbar button to the backlog tree that collapses or expands all epics and features at once.

## Behavior

1. **Default state** — all epics and features start expanded, button shows "Collapse all" with ▼ icon
2. **Collapse all** — clicking hides all features and tasks under every epic instantly
3. **Expand all** — clicking reveals all epics, features, and their backlog tasks
4. **Smart toggle** — manually collapsing any single item switches the button to "Expand all"

## Implementation

- Added `expandAll()` and `collapseAll()` functions that set/clear the `expandedEpics` and `expandedFeatures` state sets
- Toggle button placed in a new `.backlog-toolbar` div alongside the existing "Show completed" button
- `allExpanded` computed from whether all visible epics and features are in the expanded sets

## Test Results

4 new tests added, all 18 BacklogTree tests pass (14 existing + 4 new).
Full suite: 197 tests pass (193 existing + 4 new).

- renders collapse all button when tree is expanded
- collapses all epics and features when collapse all is clicked
- expands all epics and features when expand all is clicked
- shows expand all when some items are manually collapsed
