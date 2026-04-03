"""Ensure Document models are registered with SQLAlchemy Base before tests run."""

import src.document.models  # noqa: F401 — register models with Base.metadata
