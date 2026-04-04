#!/usr/bin/env python3
"""Extract the FastAPI app's OpenAPI schema to stdout as JSON.

Usage: uv run python scripts/extract-openapi.py > openapi.json
"""

import json
import sys

from src.gateway.app import create_app

app = create_app()
schema = app.openapi()
json.dump(schema, sys.stdout, indent=2, default=str)
print()  # trailing newline
