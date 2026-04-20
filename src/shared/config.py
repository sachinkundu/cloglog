from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog"
    host: str = "0.0.0.0"
    port: int = 8000
    heartbeat_timeout_seconds: int = 180  # 3 minutes
    dashboard_secret: str = "cloglog-dashboard-dev"
    mcp_service_key: str = "cloglog-mcp-dev"
    github_webhook_secret: str = ""
    review_agent_cmd: str = "codex"
    review_max_per_hour: int = 10
    review_enabled: bool = True
    review_source_root: Path | None = Field(
        default=None,
        description=(
            "Filesystem root the review engine passes to `codex -C`. "
            "Must point at a git checkout of the PR's merge target (usually main). "
            "When None, falls back to Path.cwd() — OK for dev, wrong in prod."
        ),
    )
    main_agent_inbox_path: Path | None = Field(
        default=None,
        description=(
            "Path to the main agent's inbox file. When set, PR events that cannot be "
            "resolved to a worktree agent (e.g. wt-close-* branches) fall back to "
            "appending to this file so the main agent receives them."
        ),
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
