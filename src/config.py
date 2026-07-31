"""
Configuration management using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Environment variables:
        DB_HOST: PostgreSQL host (default: 172.17.1.3)
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
    db_host: str = "172.17.1.3"
    db_port: int = 5432
    db_name: str = "cnpj_database"
    db_user: str = "postgres"
    db_password: Optional[str] = None

    # Query settings
    #
    # ⚠️ query_timeout DEVE ficar ABAIXO do `timeoutSeconds` do Cloud Run (110s).
    # Estava em 300s: o cliente levava 504 aos 110s e a query seguia rodando por
    # mais ~190s, SEGURANDO o slot de concorrência (containerConcurrency=8) e a
    # conexão do pool. Uma rajada de queries analíticas de uma sessão starvava
    # todas as outras — medido 2026-07-31: ~30min de 504 contínuo (21:24→21:54),
    # com `SELECT 1` estourando o timeout HTTP.
    #
    # Com 100s a query morre JUNTO com o request que a pediu: quem gastou o
    # tempo é quem paga, e ninguém herda trabalho abandonado.
    # Se subir o timeoutSeconds do Cloud Run, suba isto junto (nesta ordem).
    query_timeout: int = 100
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
