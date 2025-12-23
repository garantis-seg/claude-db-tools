"""
Database connection management with connection pooling
"""
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
import logging
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from .config import settings

logger = logging.getLogger(__name__)

# Global connection pool
_connection_pool: Optional[pool.ThreadedConnectionPool] = None


def init_pool() -> None:
    """
    Initialize the connection pool.
    Called automatically on first database access.
    """
    global _connection_pool

    if _connection_pool is not None:
        return

    if not settings.db_password:
        raise ValueError("DB_PASSWORD environment variable is required")

    try:
        logger.info(f"Initializing connection pool to {settings.db_host}:{settings.db_port}/{settings.db_name}")

        _connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=settings.pool_min,
            maxconn=settings.pool_max,
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            connect_timeout=settings.connect_timeout
        )

        logger.info("Connection pool initialized successfully")

    except Exception as e:
        logger.error(f"Failed to initialize connection pool: {e}")
        raise


def close_pool() -> None:
    """Close all connections in the pool."""
    global _connection_pool

    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        logger.info("Connection pool closed")


@contextmanager
def get_connection():
    """
    Context manager for database connections.
    Automatically returns connection to pool when done.

    Usage:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
    """
    global _connection_pool

    if _connection_pool is None:
        init_pool()

    conn = None
    try:
        conn = _connection_pool.getconn()
        yield conn
    finally:
        if conn and _connection_pool:
            _connection_pool.putconn(conn)


def execute_query(
    sql: str,
    params: Optional[tuple] = None,
    timeout_seconds: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Execute a SELECT query and return results as list of dicts.

    Args:
        sql: SQL query to execute
        params: Optional query parameters
        timeout_seconds: Query timeout (default: settings.query_timeout)

    Returns:
        List of result rows as dictionaries
    """
    timeout = timeout_seconds or settings.query_timeout

    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cursor.execute(f"SET statement_timeout = '{timeout}s';")
            cursor.execute(sql, params)

            if cursor.description:
                rows = cursor.fetchmany(settings.max_rows)
                return [dict(row) for row in rows]
            return []
        finally:
            cursor.close()


def execute_write(
    sql: str,
    params: Optional[tuple] = None,
    autocommit: bool = False,
    timeout_seconds: Optional[int] = None
) -> int:
    """
    Execute a write operation (INSERT, UPDATE, DELETE, DDL).

    Args:
        sql: SQL statement to execute
        params: Optional query parameters
        autocommit: Use autocommit mode (needed for CONCURRENTLY operations)
        timeout_seconds: Statement timeout (default: settings.query_timeout)

    Returns:
        Number of rows affected
    """
    timeout = timeout_seconds or settings.query_timeout

    with get_connection() as conn:
        if autocommit:
            conn.set_isolation_level(0)  # AUTOCOMMIT

        cursor = conn.cursor()
        try:
            cursor.execute(f"SET statement_timeout = '{timeout}s';")
            cursor.execute(sql, params)
            rows_affected = cursor.rowcount if cursor.rowcount >= 0 else 0

            if not autocommit:
                conn.commit()

            return rows_affected
        except Exception:
            if not autocommit:
                conn.rollback()
            raise
        finally:
            cursor.close()


def check_connection() -> bool:
    """
    Check if database connection is healthy.

    Returns:
        True if connection is working, False otherwise
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            cursor.fetchone()
            cursor.close()
            return True
    except Exception as e:
        logger.error(f"Connection check failed: {e}")
        return False
