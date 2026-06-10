"""
Query tools for executing SQL statements
"""
import json
import logging
import re
import time
from typing import Optional

from ..database import execute_query, execute_write, get_connection
from ..config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mojibake guard (incident 2026-06-10): 300k leads.meritos titles were written
# as UTF-8-read-as-CP1252 mojibake because SQL containing non-ASCII literals
# was composed/read on a Windows client (cp1252 console / open() without
# encoding) and re-encoded to UTF-8 before reaching this API. The server then
# received VALID UTF-8 of already-corrupted text and wrote it silently.
#
# Signature: a UTF-8 lead byte char (U+00C2/U+00C3 for 2-byte seqs, U+00E2 for
# punctuation 3-byte seqs) followed by a continuation byte char — either the
# raw latin-1 range U+0080-U+00BF or its CP1252 punctuation remapping (euro,
# curly quotes, dashes, etc). Legit Portuguese ("SAO PAULO", "Mérito") never
# matches: it lacks the lead+continuation DIGRAPH.
# ---------------------------------------------------------------------------
_CP1252_PUNCT = u"".join(chr(c) for c in (
    0x20AC, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6,
    0x2030, 0x0160, 0x2039, 0x0152, 0x017D, 0x2018, 0x2019, 0x201C,
    0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A,
    0x0153, 0x017E, 0x0178,
))
MOJIBAKE_SIG = re.compile(
    u"[" + chr(0xC2) + chr(0xC3) + chr(0xE2) + u"]"
    + u"[" + chr(0x80) + u"-" + chr(0xBF) + re.escape(_CP1252_PUNCT) + u"]"
)

MOJIBAKE_ERROR = (
    "SQL rejected: it contains a UTF-8-read-as-CP1252 mojibake signature "
    "(lead byte + continuation digraph, e.g. the corrupted forms of accented "
    "letters or em dash). This almost always means the SQL text was corrupted "
    "by a Windows shell/console/file-read before reaching this API — writing "
    "it would store garbage (incident 2026-06-10: 300k leads.meritos titles). "
    "Fix the client side: compose non-ASCII via chr(NNN) so the SQL stays "
    "pure ASCII, or send the statement through a path with explicit UTF-8 "
    "(e.g. requests json= from a file read with encoding='utf-8'). If you "
    "REALLY intend to write these exact mojibake characters (e.g. repairing "
    "data), pass allow_mojibake=true."
)


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


async def execute(sql: str, allow_mojibake: bool = False) -> str:
    """
    Execute a write operation (INSERT, UPDATE, DELETE, CREATE, ALTER, DROP).

    Use this tool to modify data or database structure. Supports DDL and DML statements.

    Args:
        sql: The SQL statement to execute. Must be a write operation.
            Allowed: INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, TRUNCATE, GRANT, REVOKE, COMMENT, DO
        allow_mojibake: bypass the CP1252-mojibake guard (only when intentionally
            writing mojibake characters, e.g. data repair).

    Returns:
        JSON string with execution result including rows affected and execution time.

    Examples:
        - execute("INSERT INTO my_table (col1, col2) VALUES ('a', 'b')")
        - execute("UPDATE cnpj_raw.empresas SET processed = true WHERE id = 123")
        - execute("CREATE INDEX idx_name ON cnpj_raw.empresas(razao_social)")
        - execute("DELETE FROM temp_table WHERE created_at < NOW() - INTERVAL '7 days'")
    """
    sql_upper = sql.strip().upper()

    allowed_operations = ['INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'GRANT', 'REVOKE', 'COMMENT', 'DO']

    if not any(sql_upper.startswith(op) for op in allowed_operations):
        return json.dumps({
            "success": False,
            "error": f"Only write operations allowed. Use 'query' tool for SELECT. Allowed: {', '.join(allowed_operations)}"
        })

    if not allow_mojibake and MOJIBAKE_SIG.search(sql):
        logger.warning(f"Mojibake guard rejected statement: {sql[:120]!r}")
        return json.dumps({
            "success": False,
            "mojibake_guard": True,
            "error": MOJIBAKE_ERROR,
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
