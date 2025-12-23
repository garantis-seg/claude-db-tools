"""
Configuration management using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Environment variables:
        DB_HOST: PostgreSQL host (default: 172.17.0.5)
        DB_PORT: PostgreSQL port (default: 5432)
        DB_NAME: Database name (default: cnpj_database)
        DB_USER: Database user (default: postgres)
        DB_PASSWORD: Database password (required)
        QUERY_TIMEOUT: Query timeout in seconds (default: 300)
        MAX_ROWS: Maximum rows to return (default: 10000)
        POOL_MIN: Minimum pool connections (default: 2)
        POOL_MAX: Maximum pool connections (default: 25)
    """

    # Database connection
    db_host: str = "172.17.0.5"
    db_port: int = 5432
    db_name: str = "cnpj_database"
    db_user: str = "postgres"
    db_password: Optional[str] = None

    # Query settings
    query_timeout: int = 300  # 5 minutes
    max_rows: int = 10000

    # Connection pool
    pool_min: int = 2
    pool_max: int = 25
    connect_timeout: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
