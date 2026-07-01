"""Application configuration.

All configuration comes from environment variables, loaded from a local
`.env` file if present. Nothing in this module has side effects beyond
reading the environment; secrets never appear in code or logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name!r}. "
            f"Copy .env.example to .env and fill in the values."
        )
    return value


@dataclass(frozen=True)
class Settings:
    """Typed view of the environment. Instantiate via `get_settings()`."""

    database_url: str
    adzuna_app_id: str = field(repr=False, default="")
    adzuna_app_key: str = field(repr=False, default="")
    adzuna_min_request_interval: float = 1.5
    adzuna_monthly_call_budget: int = 1000


def get_settings(require_adzuna: bool = False) -> Settings:
    """Build Settings from the environment.

    Adzuna credentials are only *required* when `require_adzuna=True`
    (i.e. for live ingestion). Analysis notebooks and tests only need
    the database URL.
    """
    return Settings(
        database_url=_require("DATABASE_URL"),
        adzuna_app_id=(
            _require("ADZUNA_APP_ID") if require_adzuna else os.environ.get("ADZUNA_APP_ID", "")
        ),
        adzuna_app_key=(
            _require("ADZUNA_APP_KEY") if require_adzuna else os.environ.get("ADZUNA_APP_KEY", "")
        ),
        adzuna_min_request_interval=float(
            os.environ.get("ADZUNA_MIN_REQUEST_INTERVAL_SECONDS", "1.5")
        ),
        adzuna_monthly_call_budget=int(os.environ.get("ADZUNA_MONTHLY_CALL_BUDGET", "1000")),
    )
