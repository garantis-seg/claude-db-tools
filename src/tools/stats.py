"""
Statistics and analysis tools
"""
import json
import logging
import re
import time
from typing import Optional

from ..database import execute_query
from .query import recusa_espinha

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
        # Os campos de pg_stat_user_tables (live_rows, dead_rows, modifications_*) sao
        # CUMULATIVOS desde `stats_reset`, e o coletor ZERA em restart do cluster --
        # 2026-08-11 15:10 UTC foi o ultimo. Sem a data ao lado, `live_rows: 0` de tabela
        # viva e indistinguivel de tabela morta. Por isso vem junto:
        #   stats_reset  -> desde quando os cumulativos contam (subtraia antes de dizer "all-time")
        #   reltuples    -> estimativa que mora em pg_class (catalogo em DISCO), sobrevive ao restart
        stats_sql = """
            SELECT
                s.schemaname,
                s.relname as table_name,
                s.n_live_tup as live_rows,
                s.n_dead_tup as dead_rows,
                s.n_mod_since_analyze as modifications_since_analyze,
                s.last_vacuum,
                s.last_autovacuum,
                s.last_analyze,
                s.last_autoanalyze,
                CASE WHEN c.reltuples < 0 THEN NULL
                     ELSE c.reltuples::bigint END as estimated_rows_reltuples,
                (SELECT stats_reset FROM pg_stat_database
                  WHERE datname = current_database()) as cumulative_counters_since
            FROM pg_stat_user_tables s
            JOIN pg_class c ON c.oid = s.relid
            WHERE s.schemaname = %s AND s.relname = %s
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
        # 🚨 `analyze=True` e o DEFAULT aqui e no handler HTTP, e `EXPLAIN ANALYZE`
        # EXECUTA o comando — inclusive DML. Sem esta linha, `EXPLAIN ANALYZE
        # DELETE FROM leads.meritos` apagava pela rota que todo mundo assume ser
        # de leitura. Modo de falha perverso: e o comando que a pessoa digita
        # JUSTAMENTE por acreditar que nao apaga.
        recusa = recusa_espinha(sql, "/api/explain")
        if recusa:
            return recusa

        # Build EXPLAIN command
        if analyze:
            explain_cmd = "EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT TEXT)"
        else:
            explain_cmd = "EXPLAIN (VERBOSE, FORMAT TEXT)"

        full_query = f"{explain_cmd} {sql}"

        logger.info(f"Running EXPLAIN on: {sql[:100]}...")
        start_time = time.time()

        # ⛔ Esta porta NAO monta o proprio caminho ate o cursor. Ela era o unico
        # `get_connection()` cru fora de `database.py`, e por isso o unico
        # caminho do servico que nunca mandava `SET statement_timeout` — `EXPLAIN
        # (ANALYZE, ...)` EXECUTA, entao era o incidente de 2026-07-31 (query
        # sobrevive ao 504 dos 110s do Cloud Run segurando slot e conexao)
        # esperando por uma query pesada.
        # ⚠️ O teto que as vezes aparecia em prod era VAZAMENTO: o `SET` que
        # `execute_write` commita fica na conexao e o proximo caller herda.
        # Medido 2026-09-09: staging 8/8 sondas leem "0", prod le "0" na 1a sonda
        # e "100s" nas 12 seguintes. Teto por sorte de pool nao e teto.
        # ponytail: `execute_query` ja E o freio (unico lugar, com o
        # `settings.query_timeout` do config) — herdar custa 2 linhas e fecha a
        # classe; mover o `SET` pro `get_connection` mexeria no caminho de TODA
        # conexao, inclusive o do autocommit recem-consertado (PR #7).
        # ponytail: o `max_retries=2` default fica. A reexecucao so dispara em
        # conexao MORTA (o EXPLAIN anterior ja nao esta rodando no servidor), e
        # nenhum caminho daqui da COMMIT — `EXPLAIN ANALYZE <dml>` e desfeito no
        # rollback do `putconn`, antes e depois deste fix.
        # ⚠️ Efeito colateral aceito: `settings.max_rows` (10.000) passa a truncar
        # o plano. Plano com >10k LINHAS de texto ja e ilegivel; o corte e visivel
        # (some o "Execution Time:" do fim) e nao vale um caminho proprio.
        # 🚨 `execute_query` usa RealDictCursor: cada linha e um dict com chave
        # "QUERY PLAN". Ler por indice posicional devolve plano vazio em silencio.
        plan_lines = [next(iter(row.values())) for row in execute_query(full_query)]

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
