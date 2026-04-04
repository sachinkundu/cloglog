"""Tests for the contract checker script."""

import json
import subprocess
import tempfile
from pathlib import Path

import yaml


def _run_checker(contracts_dir: str) -> subprocess.CompletedProcess[str]:
    """Run check-contract.py with a custom contracts directory."""
    return subprocess.run(
        ["uv", "run", "python", "scripts/check-contract.py", "--contracts-dir", contracts_dir],
        capture_output=True,
        text=True,
    )


def test_no_contract_files_skips():
    """When no contract files exist, checker exits 0."""
    with tempfile.TemporaryDirectory() as d:
        result = _run_checker(d)
        assert result.returncode == 0
        assert "No contract files found" in result.stdout


def test_matching_contract_passes():
    """When contract matches the runtime schema, checker exits 0."""
    extract = subprocess.run(
        ["uv", "run", "python", "scripts/extract-openapi.py"],
        capture_output=True,
        text=True,
    )
    runtime_schema = json.loads(extract.stdout)

    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {"/api/v1/projects": {"get": runtime_schema["paths"]["/api/v1/projects"]["get"]}},
        "components": runtime_schema.get("components", {}),
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"


def test_missing_endpoint_fails():
    """When contract defines an endpoint the backend doesn't have, checker exits 1."""
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {
            "/api/v1/nonexistent": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        }
                    }
                }
            }
        },
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 1
        assert "/api/v1/nonexistent" in result.stdout


def test_missing_response_field_fails():
    """When contract expects a field the backend response doesn't have, checker exits 1."""
    contract = {
        "openapi": "3.1.0",
        "info": {"title": "contract", "version": "0.1.0"},
        "paths": {
            "/api/v1/projects": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["id", "name", "totally_fake_field"],
                                            "properties": {
                                                "id": {"type": "string"},
                                                "name": {"type": "string"},
                                                "totally_fake_field": {"type": "string"},
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }

    with tempfile.TemporaryDirectory() as d:
        contract_path = Path(d) / "test-wave.openapi.yaml"
        contract_path.write_text(yaml.dump(contract, default_flow_style=False))
        result = _run_checker(d)
        assert result.returncode == 1
        assert "totally_fake_field" in result.stdout
