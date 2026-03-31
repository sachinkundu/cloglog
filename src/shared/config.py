from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://cloglog:cloglog_dev@localhost:5432/cloglog"
    host: str = "0.0.0.0"
    port: int = 8000
    heartbeat_timeout_seconds: int = 180  # 3 minutes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
