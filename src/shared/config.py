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
    opencode_cmd: str = "opencode"
    # T-275: default OFF. gemma4-e4b-32k (the cheapest runnable local model)
    # rubber-stamps :pass: on every diff, producing no useful signal — so
    # stage A is disabled even when the binary and PEM are both present.
    # Flip to True once T-274's agentic-mode work lands a reviewer model
    # that defends severity. No code change needed then.
    opencode_enabled: bool = False
    # Default: 32K-context variant created from a Modelfile in this repo
    # (see ``ops/opencode/Modelfile.gemma4-e4b-32k``). The stock gemma4:e4b
    # model ships with num_ctx=131072, whose KV cache will not fit on a 24 GB
    # GPU alongside other workloads (ComfyUI etc.) — the 32K variant keeps
    # the model fully on GPU, giving ~30–60 s per turn instead of 10+ min of
    # CPU-offloaded inference. See docs/setup-credentials.md for the
    # one-time ``ollama create`` step. 32K covers a near-cap PR (50K-token
    # diff cap / ``MAX_DIFF_CHARS=200_000``) — larger PRs already skip review.
    opencode_model: str = "ollama/gemma4-e4b-32k"
    opencode_max_turns: int = 5
    codex_max_turns: int = 2
    opencode_turn_timeout_seconds: float = 240.0
    review_source_root: Path | None = Field(
        default=None,
        description=(
            "Filesystem root the review engine passes to `codex -C` "
            "as the legacy single-repo fallback. Used only when "
            "`review_repo_roots` is empty (e.g. dev hosts that haven't "
            "migrated). When `review_repo_roots` is set, the resolver "
            "consults that map and refuses unconfigured repos instead "
            "of falling back here — preventing T-350 cross-repo leaks "
            "(antisocial PR #2 was reviewed against cloglog's source). "
            "When None, falls back to Path.cwd() — OK for dev, wrong in prod."
        ),
    )
    review_repo_roots: dict[str, Path] = Field(
        default_factory=dict,
        description=(
            "Per-repo filesystem map consulted by the review engine "
            "before the legacy `review_source_root` fallback. Keys are "
            "GitHub `owner/repo` strings (matching `event.repo_full_name`); "
            "values are absolute filesystem paths to the matching git "
            "checkout. When non-empty, the resolver REFUSES to review a "
            "PR whose `repo_full_name` is absent from the map and whose "
            "branch has no registered worktree on this host — see T-350. "
            "Set via the `REVIEW_REPO_ROOTS` env var as JSON: "
            '`{"sachinkundu/cloglog": "/home/sachin/code/cloglog-prod", '
            '"sachinkundu/antisocial": "/home/sachin/code/antisocial"}`.'
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
