# Work Log: wt-depgraph

**Date:** 2026-04-05
**Worktree:** wt-depgraph
**Feature:** F-18 Dependency Graph Visualization

## Tasks Completed

| Task | PR | Status |
|------|-----|--------|
| T-92: Design Spec | #34 | merged |
| T-93: Implementation Plan | #38 | merged |
| T-94: Implementation | #40 | merged |

## Commits
```
c5bb3d5 docs: add design spec for F-18 Dependency Graph Visualization
bc20585 docs: update F-18 spec to use Mermaid-to-Excalidraw rendering
3285d8c docs: add implementation plan for F-18 Dependency Graph Visualization
3c0af7f feat(board): add ORM relationships and repository methods
52d05f0 feat(board): add service layer with cycle detection
9de5875 feat(board): add dependency API routes, schemas, SSE events, and tests
5a5ec16 deps(frontend): add excalidraw and mermaid-to-excalidraw
b62a527 feat(frontend): add DependencyGraph component, hook, and API types
fad9b0f feat(frontend): add routing and Board/Dependencies view toggle
58785a6 feat(frontend): add dependency management UI in feature DetailPanel
506204f test(frontend): add DependencyGraph component tests (21 tests)
d9290d6 merge: resolve conflicts with main (search + reorder features)
```

## Files Changed
```
src/board/models.py — ORM dependencies/dependents relationships on Feature
src/board/repository.py — 5 dependency CRUD/query methods
src/board/services.py — DFS cycle detection, add/remove/graph service methods
src/board/routes.py — 3 new endpoints (graph, add dep, remove dep)
src/board/schemas.py — DependencyCreate, DependencyGraphNode/Edge/Response
src/shared/events.py — DEPENDENCY_ADDED, DEPENDENCY_REMOVED event types
tests/board/test_dependencies.py — 8 integration tests (new)
frontend/src/components/DependencyGraph.tsx — Mermaid-to-Excalidraw graph (new)
frontend/src/components/DependencyGraph.css — graph styles (new)
frontend/src/hooks/useDependencyGraph.ts — graph data + SSE hook (new)
frontend/src/components/__tests__/DependencyGraph.test.tsx — 21 tests (new)
frontend/src/api/client.ts — 3 dependency API methods
frontend/src/api/types.ts — graph types + SSE events
frontend/src/hooks/useSSE.ts — dependency event types
frontend/src/components/BoardHeader.tsx — Board/Dependencies tab toggle
frontend/src/components/Board.tsx — pass projectId to header
frontend/src/components/DetailPanel.tsx — dependency management section
frontend/src/router.tsx — /dependencies route
frontend/src/App.tsx — conditional view + dep graph data wiring
```

## Test Delta
- Pre-existing: 158 backend + 81 frontend = 239
- New: 8 backend + 21 frontend = 29
- Final: 183 backend + 102 frontend = 285
