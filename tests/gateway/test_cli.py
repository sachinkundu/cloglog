"""Tests for Gateway CLI scaffold."""

from __future__ import annotations

from typer.testing import CliRunner

from src.gateway.cli import app

runner = CliRunner()


def test_cli_version() -> None:
    """CLI --version flag prints the version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_health_command() -> None:
    """CLI health command prints status."""
    result = runner.invoke(app, ["health", "--url", "http://localhost:8000"])
    # The command should exist and accept the --url flag
    # It will fail to connect in tests, but should not crash with a CLI error
    assert result.exit_code != 2  # exit code 2 = CLI usage error


def test_cli_projects_list_command() -> None:
    """CLI projects list command exists."""
    result = runner.invoke(app, ["projects", "list", "--url", "http://localhost:8000"])
    assert result.exit_code != 2


def test_cli_projects_create_command() -> None:
    """CLI projects create command exists and requires --name."""
    result = runner.invoke(app, ["projects", "create", "--url", "http://localhost:8000"])
    # Should fail because --name is required
    assert result.exit_code == 2  # missing required option
