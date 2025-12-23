"""
Statistics and analysis tools
"""
import json
import logging
import re
import time
from typing import Optional

from ..database import execute_query, get_connection

logger = logging.getLogger(__name__)


async def get_stats(table: str, schema: str = "cnpj_raw") -> str:
    """
    Get detailed statistics for a table.

    Use this tool to understand table health, size, and maintenance status.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "cnpj_raw")

    Returns:
        JSON string with statistics including row count, size, dead tuples, and last vacuum/analyze.

    Examples:
        - get_stats("empresas")
        - get_stats("estabelecimentos", "cnpj_raw")
        - get_stats("users", "public")
    """
    try:
        # Get table statistics
        stats_sql = """
            SELECT
                schemaname,
                relname as table_name,
                n_live_tup as live_rows,
                n_dead_tup as dead_rows,
                n_mod_since_analyze as modifications_since_analyze,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze
            FROM pg_stat_user_tables
            WHERE schemaname = %s AND relname = %s
        """

        logger.info(f"Getting stats for: {schema}.{table}")
        stats_result = execute_query(stats_sql, (schema, table))

        if not stats_result:
            return json.dumps({
                "success": False,
                "error": f"Table {schema}.{table} not found"
            })

        stats = stats_result[0]

        # Get table size
        size_sql = """
            SELECT
                pg_size_pretty(pg_total_relation_size(%s)) as total_size,
                pg_size_pretty(pg_table_size(%s)) as table_size,
                pg_size_pretty(pg_indexes_size(%s)) as indexes_size
        """
        full_name = f"{schema}.{table}"
        size_result = execute_query(size_sql, (full_name, full_name, full_name))
        size_info = size_result[0] if size_result else {}

        # Get actual row count
        count_sql = f"SELECT COUNT(*) as count FROM {schema}.{table}"
        count_result = execute_query(count_sql)
        actual_rows = count_result[0]["count"] if count_result else 0

        return json.dumps({
            "success": True,
            "table": table,
            "schema": schema,
            "full_name": full_name,
            "row_count": actual_rows,
            "estimated_live_rows": stats.get("live_rows"),
            "dead_rows": stats.get("dead_rows"),
            "modifications_since_analyze": stats.get("modifications_since_analyze"),
            "size": {
                "total": size_info.get("total_size"),
                "table": size_info.get("table_size"),
                "indexes": size_info.get("indexes_size")
            },
            "maintenance": {
                "last_vacuum": stats.get("last_vacuum"),
                "last_autovacuum": stats.get("last_autovacuum"),
                "last_analyze": stats.get("last_analyze"),
                "last_autoanalyze": stats.get("last_autoanalyze")
            }
        }, default=str)

    except Exception as e:
        logger.error(f"Get stats failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })


async def explain_query(sql: str, analyze: bool = True) -> str:
    """
    Run EXPLAIN ANALYZE on a query to see execution plan.

    Use this tool to understand query performance and optimize slow queries.

    Args:
        sql: The SQL query to analyze (typically a SELECT)
        analyze: Whether to actually execute the query (default: True).
                 Set to False to only see the plan without execution.

    Returns:
        JSON string with query plan, planning time, and execution time.

    Examples:
        - explain_query("SELECT * FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
        - explain_query("SELECT e.*, est.* FROM cnpj_raw.empresas e JOIN cnpj_raw.estabelecimentos est ON e.cnpj_basico = est.cnpj_basico LIMIT 100")
        - explain_query("SELECT * FROM large_table", analyze=False)  # Just plan, no execution
    """
    try:
        # Build EXPLAIN command
        if analyze:
            explain_cmd = "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT)"
        else:
            explain_cmd = "EXPLAIN (VERBOSE, FORMAT TEXT)"

        full_query = f"{explain_cmd} {sql}"

        logger.info(f"Running EXPLAIN on: {sql[:100]}...")
        start_time = time.time()

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(full_query)
            plan_lines = [row[0] for row in cursor.fetchall()]
            cursor.close()

        execution_time = time.time() - start_time

        # Extract timing info from plan
        planning_time_ms = None
        execution_time_ms = None

        if analyze:
            for line in plan_lines:
                if "Planning Time:" in line:
                    match = re.search(r'Planning Time: ([\d.]+) ms', line)
                    if match:
                        planning_time_ms = float(match.group(1))
                elif "Execution Time:" in line:
                    match = re.search(r'Execution Time: ([\d.]+) ms', line)
                    if match:
                        execution_time_ms = float(match.group(1))

        return json.dumps({
            "success": True,
            "analyzed": analyze,
            "query": sql,
            "plan": plan_lines,
            "timing": {
                "planning_time_ms": planning_time_ms,
                "execution_time_ms": execution_time_ms,
                "total_time_ms": round(execution_time * 1000, 2)
            }
        }, default=str)

    except Exception as e:
        logger.error(f"Explain failed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })
