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


settings = Settings()
