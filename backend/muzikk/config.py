"""Environment level configuration.

Everything that can change at runtime lives in the database (see
``muzikk.services.settings``); this module only holds what has to be known
before the database is even opened.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MUZIKK_", extra="ignore")

    config_dir: Path = Path("/config")
    static_dir: Path = Path("/app/static")
    port: int = 8383
    log_level: str = "INFO"

    # Absolute container paths. They are only defaults: the admin can override
    # them from the settings page.
    music_dir: Path = Path("/music")
    downloads_dir: Path = Path("/downloads")

    # Lifetime of a session token, in hours.
    session_hours: int = 24 * 14

    # Number of download pipelines running at the same time.
    worker_concurrency: int = Field(default=2, ge=1, le=8)

    @property
    def database_path(self) -> Path:
        return self.config_dir / "muzikk.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def secret_key_path(self) -> Path:
        return self.config_dir / "secret.key"

    @property
    def jwt_key_path(self) -> Path:
        return self.config_dir / "jwt.key"

    @property
    def cache_dir(self) -> Path:
        return self.config_dir / "cache"

    @property
    def log_dir(self) -> Path:
        return self.config_dir / "logs"

    def ensure_dirs(self) -> None:
        for path in (self.config_dir, self.cache_dir, self.log_dir, self.cache_dir / "covers"):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_env_config() -> EnvConfig:
    config = EnvConfig()
    config.ensure_dirs()
    return config


def read_or_create_key(path: Path, generator=lambda: secrets.token_urlsafe(48)) -> str:
    """Return the key stored at ``path``, creating it on first start."""
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return content
    path.parent.mkdir(parents=True, exist_ok=True)
    value = generator()
    path.write_text(value, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        # Windows and some network filesystems do not support this.
        pass
    return value
