"""CLI scaffold for cloglog using Typer."""

from typing import Annotated

import httpx
import typer

app = typer.Typer(name="cloglog", help="CLI for the cloglog Kanban dashboard.")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo("cloglog 0.1.0")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    """cloglog — Multi-project Kanban dashboard for AI coding agents."""


@app.command()
def health(
    url: Annotated[
        str, typer.Option(help="Base URL of the cloglog server")
    ] = "http://localhost:8000",
) -> None:
    """Check server health."""
    try:
        resp = httpx.get(f"{url}/health", timeout=5.0)
        data = resp.json()
        typer.echo(f"Status: {data.get('status', 'unknown')}")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None


# --- Projects subcommand ---

projects_app = typer.Typer(name="projects", help="Manage projects.")
app.add_typer(projects_app)


@projects_app.command("list")
def projects_list(
    url: Annotated[str, typer.Option(help="Base URL")] = "http://localhost:8000",
    api_key: Annotated[str, typer.Option(help="Project API key", envvar="CLOGLOG_API_KEY")] = "",
) -> None:
    """List all projects."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        resp = httpx.get(f"{url}/api/v1/projects", headers=headers, timeout=5.0)
        for project in resp.json():
            typer.echo(f"  {project['id']}  {project['name']}  [{project['status']}]")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None


@projects_app.command("create")
def projects_create(
    name: Annotated[str, typer.Option(help="Project name")],
    url: Annotated[str, typer.Option(help="Base URL")] = "http://localhost:8000",
    description: Annotated[str, typer.Option(help="Project description")] = "",
) -> None:
    """Create a new project."""
    try:
        resp = httpx.post(
            f"{url}/api/v1/projects",
            json={"name": name, "description": description},
            timeout=5.0,
        )
        data = resp.json()
        typer.echo(f"Created project: {data['id']}")
        if "api_key" in data:
            typer.echo(f"API Key (save this!): {data['api_key']}")
    except httpx.ConnectError:
        typer.echo(f"Error: cannot connect to {url}", err=True)
        raise typer.Exit(code=1) from None
