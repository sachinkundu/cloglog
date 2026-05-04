"""Text sanitization utilities shared across contexts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


def strip_nul(obj: Any) -> Any:
    """Recursively strip NUL bytes (U+0000) from all strings in a JSON-like structure.

    PostgreSQL TEXT and JSONB cannot store NUL bytes. Codex/opencode subprocess
    output may contain them (e.g. from binary-embedded strings or malformed JSON).
    Apply at any chokepoint before persisting free-form text.
    """
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {k: strip_nul(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_nul(item) for item in obj]
    return obj


class NulSanitizedModel(BaseModel):
    """Pydantic base that strips NUL bytes from all string fields before validation.

    PostgreSQL TEXT columns reject U+0000. Applied to every write schema
    (Create/Update) so the sanitization happens at one chokepoint regardless
    of which endpoint or MCP tool is the caller. T-407.
    """

    @model_validator(mode="before")
    @classmethod
    def _strip_nul_from_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: strip_nul(v) if isinstance(v, str) else v for k, v in data.items()}
        return data
