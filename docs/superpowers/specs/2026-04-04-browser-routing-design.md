# Browser Routing with URL State Persistence

**Date:** 2026-04-04
**Status:** Design approved
**Task:** T-52 (Board Redesign > UI Improvements)

## Problem

The app uses React `useState` for navigation. Refreshing the page loses the selected project and any open detail panel. Browser back/forward buttons don't work.

## Design

### Library

`react-router-dom` v7.

### Routes

| Path | View |
|------|------|
| `/` | Redirect to board (no project selected) |
| `/projects/:projectId` | Board view for a project |
| `/projects/:projectId/epics/:epicId` | Board + epic detail panel |
| `/projects/:projectId/features/:featureId` | Board + feature detail panel |
| `/projects/:projectId/tasks/:taskId` | Board + task detail panel |

### Implementation

- New `frontend/src/router.tsx` — route definitions using `createBrowserRouter`
- `App.tsx` — restructured to use `useParams` and `useNavigate` instead of `useState` for `selectedProjectId` and `detail`
- `Sidebar.tsx` — uses `navigate` or `<Link>` for project selection instead of `onSelectProject` callback
- `Layout.tsx` — minor prop adjustment since project selection comes from URL

### What doesn't change

`Board.tsx`, `BacklogTree.tsx`, `DetailPanel.tsx`, `TaskCard.tsx`, `BreadcrumbPills.tsx` — these receive data as props and are unaffected by the routing change.

### Vite configuration

Vite's SPA dev server already serves `index.html` for all routes. No config change needed.

## Out of Scope

- Encoding transient UI state in URL (collapsed epics, selected agent filter)
- Server-side rendering
- URL-based board filtering
