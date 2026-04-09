#!/usr/bin/env python3
"""Validate that the FastAPI backend matches the designed API contracts.

Compares the runtime OpenAPI schema against all contract files in
docs/contracts/*.openapi.yaml. Exits non-zero if any differences found.

Usage:
    uv run python scripts/check-contract.py
    uv run python scripts/check-contract.py --contracts-dir path/to/contracts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from src.gateway.app import create_app


def load_runtime_schema() -> dict:
    """Extract the current OpenAPI schema from FastAPI."""
    app = create_app()
    return app.openapi()


def load_contracts(contracts_dir: Path) -> dict:
    """Load and merge all contract YAML files."""
    merged_paths: dict = {}
    merged_components: dict = {}

    for f in sorted(contracts_dir.glob("*.openapi.yaml")):
        with open(f) as fh:
            contract = yaml.safe_load(fh)
        merged_paths.update(contract.get("paths", {}))
        for key, val in contract.get("components", {}).items():
            if key not in merged_components:
                merged_components[key] = {}
            merged_components[key].update(val)

    return {"paths": merged_paths, "components": merged_components}


def resolve_ref(ref: str, schema: dict) -> dict:
    """Resolve a $ref pointer like '#/components/schemas/Foo'."""
    parts = ref.lstrip("#/").split("/")
    node = schema
    for part in parts:
        node = node[part]
    return node


def get_response_properties(
    endpoint_schema: dict, full_schema: dict
) -> dict[str, set[str]]:
    """Extract response field names per status code from an endpoint schema."""
    result: dict[str, set[str]] = {}
    for status_code, resp in endpoint_schema.get("responses", {}).items():
        content = resp.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})
        result[status_code] = _extract_field_names(schema, full_schema)
    return result


def _extract_field_names(schema: dict, full_schema: dict) -> set[str]:
    """Recursively extract field names from a schema, resolving $ref."""
    if "$ref" in schema:
        schema = resolve_ref(schema["$ref"], full_schema)

    # Array — look at items
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return _extract_field_names(items, full_schema)

    # Object with properties
    props = schema.get("properties", {})
    return set(props.keys())


def check_endpoint(
    path: str,
    method: str,
    contract_op: dict,
    runtime_op: dict,
    contract_full: dict,
    runtime_full: dict,
) -> list[str]:
    """Compare a single endpoint between contract and runtime. Returns errors."""
    errors: list[str] = []

    contract_responses = get_response_properties(contract_op, contract_full)
    runtime_responses = get_response_properties(runtime_op, runtime_full)

    for status_code, contract_fields in contract_responses.items():
        if not contract_fields:
            continue

        runtime_fields = runtime_responses.get(status_code, set())
        if not runtime_fields:
            continue

        missing = contract_fields - runtime_fields
        if missing:
            errors.append(
                f"  {method.upper()} {path} [{status_code}]: "
                f"contract expects fields {sorted(missing)} but backend response is missing them. "
                f"Backend has: {sorted(runtime_fields)}"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check API contract compliance")
    parser.add_argument(
        "--contracts-dir",
        default="docs/contracts",
        help="Directory containing *.openapi.yaml contract files",
    )
    args = parser.parse_args()

    contracts_dir = Path(args.contracts_dir)
    if not contracts_dir.exists() or not list(contracts_dir.glob("*.openapi.yaml")):
        print("No contract files found, skipping contract check")
        return 0

    runtime = load_runtime_schema()
    contract = load_contracts(contracts_dir)

    errors: list[str] = []
    warnings: list[str] = []

    for path, methods in contract["paths"].items():
        runtime_path = runtime.get("paths", {}).get(path)

        if runtime_path is None:
            errors.append(f"  MISSING endpoint: {path} (defined in contract, not in backend)")
            continue

        for method, contract_op in methods.items():
            if method in ("parameters", "summary", "description"):
                continue

            runtime_op = runtime_path.get(method)
            if runtime_op is None:
                errors.append(f"  MISSING method: {method.upper()} {path}")
                continue

            contract_full = {
                "components": contract.get("components", {}),
                "paths": contract["paths"],
            }
            runtime_full = {
                "components": runtime.get("components", {}),
                "paths": runtime.get("paths", {}),
            }

            endpoint_errors = check_endpoint(
                path, method, contract_op, runtime_op, contract_full, runtime_full
            )
            errors.extend(endpoint_errors)

    if errors:
        print("CONTRACT CHECK FAILED\n")
        for e in errors:
            print(e)
        if warnings:
            print("\nWarnings:")
            for w in warnings:
                print(w)
        return 1

    print("Contract check passed — backend matches all contract specifications")
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
