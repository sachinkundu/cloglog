---
name: db-migration
description: Create an Alembic migration safely — checks revision chain, generates migration, validates it compiles. Use when adding/modifying database models.
---

# Database Migration

Create Alembic migrations with proper revision chain handling.

## When to Use

- Adding a new model or table
- Adding/removing/modifying columns
- Adding indexes or constraints
- Any change to SQLAlchemy models in `src/*/models.py`

## Workflow

### 1. Verify Current State

```bash
# Check the current migration head
uv run alembic heads

# Check full history to understand the chain
uv run alembic history --verbose | head -20

# Verify DB is up to date
uv run alembic current
```

### 2. Generate the Migration

```bash
# Auto-generate from model changes
uv run alembic revision --autogenerate -m "<description>"
```

Use descriptive messages: `"add pr_merged to tasks"`, `"create notifications table"`, `"add position to features"`.

### 3. Review and Fix the Migration

After generation, ALWAYS read the migration file and verify:

1. **`down_revision`** points to the actual current head, not a stale one. In worktrees, another context may have merged a migration. Check with `uv run alembic heads`.

2. **The upgrade/downgrade functions** are correct — autogenerate sometimes misses things (especially for renamed columns, data migrations, or complex constraints).

3. **No destructive operations** without explicit intent — `drop_column`, `drop_table`, `drop_index` should be intentional.

4. **Nullable defaults** — new non-nullable columns on existing tables need a `server_default` or a data migration step.

### 4. Test the Migration

```bash
# Apply the migration
uv run alembic upgrade head

# Run tests to verify models match schema
uv run pytest tests/ -x -q --tb=short

# If something went wrong, downgrade
uv run alembic downgrade -1
```

### 5. Worktree-Specific Rules

- **Never commit the migration without rebasing first.** If another worktree merged a migration while you worked, your `down_revision` is stale. Rebase, update the revision pointer, and re-test.
- **One migration per PR.** Don't batch multiple schema changes into one migration — it makes rollback harder.
- **Model imports in conftest.py.** If you added a new model, verify it's imported in `tests/conftest.py` so `Base.metadata.create_all` creates the table in test DBs.

## Common Patterns

### Adding a column with default

```python
# In the migration
op.add_column('tasks', sa.Column('pr_merged', sa.Boolean(), nullable=False, server_default='false'))
```

### Adding a FK constraint

```python
op.add_column('worktrees', sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False))
```

### Creating a new table

Prefer defining the model in `src/<context>/models.py` first, then auto-generating.
