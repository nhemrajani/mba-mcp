"""Configuration. Every secret comes from the environment — never hardcoded."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = "~/.mba-mcp"
DEFAULT_TRACK = "consulting"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration.

    Read once per process via :func:`get_config`; every field is derived from
    the environment (or the MCP client's server ``env`` block).
    """

    data_dir: Path
    track: str
    school: str | None
    adzuna_app_id: str | None
    adzuna_app_key: str | None
    adzuna_country: str
    gmail_client_secret: Path
    gmail_token: Path
    base_cv: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mba.db"

    @property
    def timeline_overrides_dir(self) -> Path:
        return self.data_dir / "timelines"

    @property
    def adzuna_enabled(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


def load_config() -> Config:
    data_dir = _env_path("MBA_MCP_DATA_DIR") or Path(DEFAULT_DATA_DIR).expanduser()
    return Config(
        data_dir=data_dir,
        track=os.environ.get("MBA_MCP_TRACK", DEFAULT_TRACK).strip().lower() or DEFAULT_TRACK,
        school=os.environ.get("MBA_MCP_SCHOOL", "").strip() or None,
        adzuna_app_id=os.environ.get("ADZUNA_APP_ID", "").strip() or None,
        adzuna_app_key=os.environ.get("ADZUNA_APP_KEY", "").strip() or None,
        adzuna_country=os.environ.get("ADZUNA_COUNTRY", "us").strip().lower() or "us",
        gmail_client_secret=_env_path("GMAIL_OAUTH_CLIENT_SECRET")
        or data_dir / "gmail_client_secret.json",
        gmail_token=_env_path("GMAIL_TOKEN_PATH") or data_dir / "gmail_token.json",
        base_cv=_env_path("MBA_MCP_BASE_CV") or data_dir / "base_cv.md",
    )


_config: Config | None = None


def get_config(refresh: bool = False) -> Config:
    global _config
    if _config is None or refresh:
        _config = load_config()
    return _config
