#!/usr/bin/env python3
"""Extract the FastAPI app's OpenAPI schema to stdout as JSON.

Usage: uv run python scripts/extract-openapi.py > openapi.json
"""

import json
import os
import sys

# T-388: importing create_app() constructs Settings at import time, which
# now requires DATABASE_URL. Seed a placeholder so this script works on a
# fresh clone — schema extraction never opens a DB connection.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/postgres",
)

from src.gateway.app import create_app

app = create_app()
schema = app.openapi()
json.dump(schema, sys.stdout, indent=2, default=str)
print()  # trailing newline
