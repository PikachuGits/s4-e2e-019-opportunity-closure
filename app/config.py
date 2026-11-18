"""Runtime configuration.

Every value comes from environment variables only (no secrets in code, no
client names in configuration defaults).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "sqlite+pysqlite:///./.data/e2e.sqlite3",
    )
    # The harness creates the schema on startup so the E2E suite can run with a
    # throw-away database. A real deployment runs `alembic upgrade head` instead
    # and keeps AUTO_CREATE_SCHEMA disabled.
    auto_create_schema: bool = os.getenv("AUTO_CREATE_SCHEMA", "1") == "1"
    seed_demo_data: bool = os.getenv("SEED_DEMO_DATA", "1") == "1"


settings = Settings()
