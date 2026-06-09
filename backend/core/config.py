"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CodeOrbit API"
    app_version: str = "1.0.0"
    debug: bool = False

    # 🚨 IMPORTANT: No fallback DB (forces Neon in production)
    database_url: str | None = None

    # folders
    data_dir: Path = BASE_DIR / "data"
    uploads_dir: Path = BASE_DIR / "data" / "uploads"
    states_dir: Path = BASE_DIR / "data" / "states"
    repos_dir: Path = BASE_DIR / "data" / "repositories"

    max_upload_size_mb: int = 100
    max_analysis_retries: int = 3
    analysis_poll_interval_ms: int = 500

    cors_origins: str = (
        "http://localhost:3000,"
        "http://localhost:5173,"
        "https://your-vercel-app.vercel.app"
    )

    run_migrations_on_startup: bool = True

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        """Fail fast if required production config is missing."""
        if not self.database_url:
            raise ValueError(
                "DATABASE_URL is missing. Set it in environment (Neon Postgres required)."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings