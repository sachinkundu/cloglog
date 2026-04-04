# Entity Numbering

**Date:** 2026-04-04
**Status:** Design approved
**Feature:** Board Redesign > Entity Numbering

## Problem

Epics, features, and tasks are only identifiable by UUID or title. Users need short, stable identifiers to reference items in conversation ("fix T-37", "what's the status of E-2").

## Design

### Data Model

Add an integer `number` column to `epics`, `features`, and `tasks` tables. Each entity type has its own independent sequence scoped to the project:

- Epics: next = max(number) across project's epics + 1
- Features: next = max(number) across all features in the project + 1
- Tasks: next = max(number) across all tasks in the project + 1

The column stores a bare integer. The display prefix (`E-`, `F-`, `T-`) is a frontend/display convention, not stored in the database.

Default column value is 0. An Alembic migration backfills existing rows by assigning numbers in `created_at` order per entity type within each project.

### API Changes

Add `number: int` to these response schemas:

- `EpicResponse`
- `FeatureResponse`
- `TaskResponse` / `TaskCard`
- `BacklogTask`

No new endpoints. Existing create endpoints and the import endpoint auto-assign the next number and return it. MCP tools inherit this since they wrap the same API.

### Auto-Assignment

Repository methods `create_epic`, `create_feature`, `create_task` query `max(number)` for the entity type within the project and assign `max + 1`. The `import_plan` bulk create method assigns numbers sequentially within the batch, starting from the current max.

### Frontend Display

Numbers shown with type prefix in three places:

- **BacklogTree**: Before title — "E-1 Auth System", "F-3 OAuth", "T-37 Add callback". Number in muted color.
- **BreadcrumbPills**: In pill text — "E-1 Auth System" pill, "F-3 OAuth" pill.
- **DetailPanel**: Next to title header — "T-37" in muted text.

A helper function `formatEntityNumber(type, number)` returns the formatted string.

## Out of Scope

- Renumbering after deletion (numbers are stable, gaps are acceptable)
- Custom number prefixes per project
- Cross-project references
