"""
Schema tools for database introspection
"""
import json
import logging
from typing import Optional

from ..database import execute_query

logger = logging.getLogger(__name__)


async def list_tables(schema: str = "public") -> str:
    """
    List all tables in a schema with row counts and sizes.

    Use this tool to discover what tables exist in the database.

    Args:
        schema: Schema name to list tables from (default: "public").
                Common schemas: "public", "cnpj_raw"

    Returns:
        JSON string with list of tables including name, row count, and size.

    Examples:
        - list_tables()  # Lists tables in public schema
        - list_tables("cnpj_raw")  # Lists tables in cnpj_raw schema
    """
    try:
        sql = """
            SELECT
                t.tablename as table_name,
                pg_size_pretty(pg_total_relation_size(quote_ident(t.schemaname) || '.' || quote_ident(t.tablename))) as size,
                COALESCE(s.n_live_tup, 0) as estimated_rows
            FROM pg_tables t
            LEFT JOIN pg_stat_user_tables s
                ON t.schemaname = s.schemaname AND t.tablename = s.relname
            WHERE t.schemaname = %s
            ORDER BY t.tablename
        """

        logger.info(f"Listing tables in schema: {schema}")
        results = execute_query(sql, (schema,))

        return json.dumps({
            "success": True,
            "schema": schema,
            "tables": results,
            "total_tables": len(results)
        }, default=str)

    except Exception as e:
        logger.error(f"List tables failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def get_schema(table: str, schema: str = "public") -> str:
    """
    Get detailed schema information for a table.

    Use this tool to understand the structure of a table including columns, types, and constraints.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "public")

    Returns:
        JSON string with column details including name, type, nullability, and default values.

    Examples:
        - get_schema("empresas", "cnpj_raw")
        - get_schema("users")  # Uses public schema
        - get_schema("estabelecimentos", "cnpj_raw")
    """
    try:
        # Get column information
        columns_sql = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """

        logger.info(f"Getting schema for: {schema}.{table}")
        columns = execute_query(columns_sql, (schema, table))

        if not columns:
            return json.dumps({
                "success": False,
                "error": f"Table {schema}.{table} not found"
            })

        # Get row count estimate
        count_sql = f"SELECT COUNT(*) as count FROM {schema}.{table}"
        try:
            count_result = execute_query(count_sql)
            row_count = count_result[0]["count"] if count_result else 0
        except Exception:
            row_count = "unknown"

        # Format columns for better readability
        formatted_columns = []
        for col in columns:
            formatted_columns.append({
                "name": col["column_name"],
                "type": col["data_type"],
                "nullable": col["is_nullable"] == "YES",
                "default": col["column_default"],
                "max_length": col["character_maximum_length"]
            })

        return json.dumps({
            "success": True,
            "table": table,
            "schema": schema,
            "full_name": f"{schema}.{table}",
            "row_count": row_count,
            "columns": formatted_columns
        }, default=str)

    except Exception as e:
        logger.error(f"Get schema failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def get_indexes(table: Optional[str] = None, schema: str = "cnpj_raw") -> str:
    """
    List indexes for a table or entire schema.

    Use this tool to understand what indexes exist and their sizes.

    Args:
        table: Optional table name to filter indexes. If not provided, lists all indexes in schema.
        schema: Schema name (default: "cnpj_raw")

    Returns:
        JSON string with index details including name, table, type, and size.

    Examples:
        - get_indexes()  # All indexes in cnpj_raw schema
        - get_indexes("empresas")  # Indexes on empresas table
        - get_indexes(schema="public")  # All indexes in public schema
    """
    try:
        where_clause = "AND pi.tablename = %s" if table else ""
        params = (schema, table) if table else (schema,)

        sql = f"""
            SELECT
                pi.tablename as table_name,
                pi.indexname as index_name,
                pg_size_pretty(pg_relation_size(quote_ident(pi.schemaname) || '.' || quote_ident(pi.indexname))) as size,
                am.amname as index_type,
                pi.indexdef as definition
            FROM pg_indexes pi
            JOIN pg_class c ON c.relname = pi.indexname AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = pi.schemaname)
            JOIN pg_am am ON am.oid = c.relam
            WHERE pi.schemaname = %s
            {where_clause}
            ORDER BY pi.tablename, pi.indexname
        """

        logger.info(f"Getting indexes for schema: {schema}, table: {table or 'all'}")
        results = execute_query(sql, params)

        return json.dumps({
            "success": True,
            "schema": schema,
            "table": table,
            "indexes": results,
            "total_indexes": len(results)
        }, default=str)

    except Exception as e:
        logger.error(f"Get indexes failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
