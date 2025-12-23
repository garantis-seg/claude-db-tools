"""
Data sampling tools
"""
import json
import logging
from typing import Optional

from ..database import execute_query

logger = logging.getLogger(__name__)


async def get_sample(table: str, schema: str = "public", limit: int = 10) -> str:
    """
    Get sample rows from a table.

    Use this tool to quickly preview data in a table without writing SQL.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "public")
        limit: Number of rows to return (default: 10, max: 100)

    Returns:
        JSON string with sample rows, columns, and row count.

    Examples:
        - get_sample("empresas", "cnpj_raw")
        - get_sample("users")  # Uses public schema, 10 rows
        - get_sample("estabelecimentos", "cnpj_raw", limit=50)
    """
    try:
        # Enforce max limit
        effective_limit = min(limit, 100)

        # Check if table exists
        check_sql = """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """
        check_result = execute_query(check_sql, (schema, table))

        if not check_result:
            return json.dumps({
                "success": False,
                "error": f"Table {schema}.{table} not found"
            })

        # Get sample data
        sample_sql = f"SELECT * FROM {schema}.{table} LIMIT %s"

        logger.info(f"Getting sample from: {schema}.{table} (limit: {effective_limit})")
        results = execute_query(sample_sql, (effective_limit,))

        columns = list(results[0].keys()) if results else []

        return json.dumps({
            "success": True,
            "table": table,
            "schema": schema,
            "full_name": f"{schema}.{table}",
            "rows_returned": len(results),
            "columns": columns,
            "data": results
        }, default=str)

    except Exception as e:
        logger.error(f"Get sample failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
