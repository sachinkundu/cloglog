"""Pin the ``.github/codex/review-schema.json`` shape against OpenAI's
Structured Outputs rule.

OpenAI rejects response_format schemas unless **every** property in
``properties`` is listed in ``required``. Optionality is expressed via
``"type": ["<type>", "null"]``, not by omission from ``required``.

Before T-264, the ``status`` property was in ``properties`` but not in
``required``. OpenAI returned ``400 invalid_json_schema`` on every codex
call and the codex reviewer posted zero reviews between 2026-04-23T05:32
and the fix. This module pins the invariant so a future schema edit
that forgets to update ``required`` fails fast at test time.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parents[2] / ".github" / "codex" / "review-schema.json"


def _collect_all_object_schemas(node: object) -> list[dict]:
    """Walk the schema document and return every object-typed subschema."""
    out: list[dict] = []
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "object" or (isinstance(node_type, list) and "object" in node_type):
            out.append(node)
        for value in node.values():
            out.extend(_collect_all_object_schemas(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_collect_all_object_schemas(item))
    return out


class TestReviewSchemaOpenAICompatibility:
    """Every object schema in ``review-schema.json`` must satisfy OpenAI's
    Structured Outputs rule — every key in ``properties`` must be in
    ``required``. Nullable fields use ``"type": ["string", "null"]``."""

    def test_schema_file_exists(self) -> None:
        assert SCHEMA_PATH.is_file(), f"missing {SCHEMA_PATH}"

    def test_every_object_schema_requires_all_its_properties(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text())
        violations: list[str] = []
        for sub in _collect_all_object_schemas(schema):
            properties = sub.get("properties")
            if not properties:
                continue
            required = set(sub.get("required", []))
            missing = set(properties.keys()) - required
            if missing:
                violations.append(f"object schema missing from required: {sorted(missing)}")
        assert not violations, (
            "OpenAI Structured Outputs rejects schemas where not every "
            "property is in `required`. Violations:\n  "
            + "\n  ".join(violations)
            + "\nFix: either add each missing key to the parent's "
            '`required` (and use `type: ["<type>", "null"]` for '
            "optionality), or drop the property."
        )

    def test_status_is_required_and_nullable(self) -> None:
        """Regression guard for T-264 specifically — ``status`` was the
        property that tripped the bug. Pin both that it's required and
        that its type allows null."""
        schema = json.loads(SCHEMA_PATH.read_text())
        required = schema.get("required", [])
        assert "status" in required, (
            "`status` must be in top-level `required` per OpenAI "
            'Structured Outputs rule. Optionality via `type: ["string", "null"]`.'
        )
        status_schema = schema["properties"]["status"]
        status_type = status_schema.get("type")
        assert isinstance(status_type, list) and "null" in status_type, (
            f"`status.type` must be a list containing 'null', got: {status_type!r}. "
            'A plain `type: "string"` requires a non-null value.'
        )

    def test_additional_properties_false_on_every_object(self) -> None:
        """OpenAI also requires ``additionalProperties: false`` on every
        object. Loose schemas are rejected."""
        schema = json.loads(SCHEMA_PATH.read_text())
        violations: list[str] = []
        for sub in _collect_all_object_schemas(schema):
            if sub.get("properties") and sub.get("additionalProperties") is not False:
                violations.append(
                    f"object without `additionalProperties: false`: "
                    f"properties={sorted(sub['properties'].keys())}"
                )
        assert not violations, "\n".join(violations)
