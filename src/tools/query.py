"""
Query tools for executing SQL statements
"""
import json
import logging
import time
from typing import Optional

from ..database import execute_query, execute_write, get_connection
from ..config import settings

logger = logging.getLogger(__name__)


async def query(sql: str, limit: int = 1000) -> str:
    """
    Execute a SELECT query and return results.

    Use this tool to read data from the database. Supports any valid SELECT statement.

    Args:
        sql: The SELECT query to execute. Must be a valid SQL SELECT statement.
        limit: Maximum number of rows to return (default: 1000, max: 10000).

    Returns:
        JSON string with query results including columns, data, row count, and execution time.

    Examples:
        - query("SELECT * FROM cnpj_raw.empresas LIMIT 10")
        - query("SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
        - query("SELECT COUNT(*) as total FROM cnpj_raw.estabelecimentos")
    """
    sql_upper = sql.strip().upper()

    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return json.dumps({
            "success": False,
            "error": "Only SELECT queries allowed. Use 'execute' tool for write operations."
        })

    # Enforce limit
    effective_limit = min(limit, settings.max_rows)

    # Add LIMIT if not present
    if "LIMIT" not in sql_upper:
        sql = f"{sql.rstrip(';')} LIMIT {effective_limit}"

    try:
        logger.info(f"Executing query: {sql[:100]}...")
        start_time = time.time()

        results = execute_query(sql)
        execution_time = time.time() - start_time

        columns = list(results[0].keys()) if results else []

        return json.dumps({
            "success": True,
            "rows": len(results),
            "columns": columns,
            "data": results,
            "execution_time_ms": round(execution_time * 1000, 2)
        }, default=str)

    except Exception as e:
        logger.error(f"Query failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def execute(sql: str) -> str:
    """
    Execute a write operation (INSERT, UPDATE, DELETE, CREATE, ALTER, DROP).

    Use this tool to modify data or database structure. Supports DDL and DML statements.

    Args:
        sql: The SQL statement to execute. Must be a write operation.
            Allowed: INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, TRUNCATE, GRANT, REVOKE

    Returns:
        JSON string with execution result including rows affected and execution time.

    Examples:
        - execute("INSERT INTO my_table (col1, col2) VALUES ('a', 'b')")
        - execute("UPDATE cnpj_raw.empresas SET processed = true WHERE id = 123")
        - execute("CREATE INDEX idx_name ON cnpj_raw.empresas(razao_social)")
        - execute("DELETE FROM temp_table WHERE created_at < NOW() - INTERVAL '7 days'")
    """
    sql_upper = sql.strip().upper()

    allowed_operations = ['INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'GRANT', 'REVOKE']

    if not any(sql_upper.startswith(op) for op in allowed_operations):
        return json.dumps({
            "success": False,
            "error": f"Only write operations allowed. Use 'query' tool for SELECT. Allowed: {', '.join(allowed_operations)}"
        })

    # Check if autocommit is needed
    needs_autocommit = "CONCURRENTLY" in sql_upper

    try:
        logger.info(f"Executing statement: {sql[:100]}...")
        start_time = time.time()

        rows_affected = execute_write(sql, autocommit=needs_autocommit)
        execution_time = time.time() - start_time

        return json.dumps({
            "success": True,
            "rows_affected": rows_affected,
            "execution_time_ms": round(execution_time * 1000, 2),
            "message": f"Statement executed successfully. {rows_affected} rows affected."
        })

    except Exception as e:
        logger.error(f"Execute failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def count(table: str, where: Optional[str] = None) -> str:
    """
    Count rows in a table with optional WHERE clause.

    Use this tool for quick row counts without fetching data.

    Args:
        table: Full table name including schema (e.g., "cnpj_raw.empresas")
        where: Optional WHERE clause without the WHERE keyword (e.g., "situacao_cadastral = '02'")

    Returns:
        JSON string with the count and execution time.

    Examples:
        - count("cnpj_raw.empresas")
        - count("cnpj_raw.estabelecimentos", where="situacao_cadastral = '02'")
        - count("public.users", where="active = true AND created_at > '2024-01-01'")
    """
    try:
        if where:
            sql = f"SELECT COUNT(*) as count FROM {table} WHERE {where}"
        else:
            sql = f"SELECT COUNT(*) as count FROM {table}"

        logger.info(f"Counting rows: {sql}")
        start_time = time.time()

        results = execute_query(sql)
        execution_time = time.time() - start_time

        row_count = results[0]["count"] if results else 0

        return json.dumps({
            "success": True,
            "table": table,
            "count": row_count,
            "where": where,
            "execution_time_ms": round(execution_time * 1000, 2)
        })

    except Exception as e:
        logger.error(f"Count failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
