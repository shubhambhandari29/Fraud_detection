"""Environment-based application configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    """Runtime settings loaded from environment variables."""

    DB_SERVER: str | None = os.getenv("DB_SERVER")
    DB_NAME: str = os.getenv("DB_NAME", "CLMDS_DataModelingAndTextMining")
    DB_DRIVER: str = os.getenv("DB_DRIVER", "{ODBC Driver 18 for SQL Server}")
    DB_AUTH: str | None = os.getenv("DB_AUTH")
    DB_CONNECTION_TIMEOUT: int = int(os.getenv("DB_CONNECTION_TIMEOUT", "15"))

    # Temporary JWT authentication configuration
    SECRET_KEY: str = os.getenv("SECRET_KEY", "development-only-change-me")
    ACCESS_TOKEN_VALIDITY: int = int(os.getenv("ACCESS_TOKEN_VALIDITY", "30"))
    REFRESH_TOKEN_VALIDITY: int = int(os.getenv("REFRESH_TOKEN_VALIDITY", "10080"))
    SECURE_COOKIE: bool = os.getenv("SECURE_COOKIE", "false").strip().lower() == "true"
    SAME_SITE: str = os.getenv("SAME_SITE", "lax")


settings = Settings()
