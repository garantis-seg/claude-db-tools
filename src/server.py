"""
claude-db-tools MCP Server

MCP Server for PostgreSQL access - Tools for Claude Code to interact with Cloud SQL databases.

Usage:
    # Local development (stdio transport)
    python -m src.server

    # HTTP transport (Cloud Run)
    MCP_TRANSPORT=http python -m src.server
"""
import logging
import sys
import os
import json
from mcp.server.fastmcp import FastMCP

from .database import init_pool, close_pool, check_connection
from .tools.query import query, execute, count
from .tools.schema import list_tables, get_schema, get_indexes
from .tools.stats import get_stats, explain_query
from .tools.sample import get_sample

# Configure logging to stderr (required for MCP - stdout is for JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Create MCP server
mcp = FastMCP("claude-db-tools")


# Register all tools
@mcp.tool()
async def db_query(sql: str, limit: int = 1000) -> str:
    """
    Execute a SELECT query and return results.

    Use this tool to read data from the database. Supports any valid SELECT statement.

    Args:
        sql: The SELECT query to execute. Must be a valid SQL SELECT statement.
        limit: Maximum number of rows to return (default: 1000, max: 10000).

    Returns:
        JSON string with query results including columns, data, row count, and execution time.

    Examples:
        - db_query("SELECT * FROM cnpj_raw.empresas LIMIT 10")
        - db_query("SELECT cnpj_basico, razao_social FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
    """
    return await query(sql, limit)


@mcp.tool()
async def db_execute(sql: str) -> str:
    """
    Execute a write operation (INSERT, UPDATE, DELETE, CREATE, ALTER, DROP).

    Use this tool to modify data or database structure.

    Args:
        sql: The SQL statement to execute.
            Allowed: INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, TRUNCATE, GRANT, REVOKE

    Returns:
        JSON string with execution result including rows affected.

    Examples:
        - db_execute("INSERT INTO my_table (col1) VALUES ('value')")
        - db_execute("CREATE INDEX idx_name ON table(column)")
    """
    return await execute(sql)


@mcp.tool()
async def db_count(table: str, where: str = None) -> str:
    """
    Count rows in a table with optional WHERE clause.

    Args:
        table: Full table name including schema (e.g., "cnpj_raw.empresas")
        where: Optional WHERE clause without the WHERE keyword

    Returns:
        JSON string with the count.

    Examples:
        - db_count("cnpj_raw.empresas")
        - db_count("cnpj_raw.estabelecimentos", "situacao_cadastral = '02'")
    """
    return await count(table, where)


@mcp.tool()
async def db_list_tables(schema: str = "public") -> str:
    """
    List all tables in a schema with row counts and sizes.

    Args:
        schema: Schema name (default: "public"). Common: "public", "cnpj_raw"

    Returns:
        JSON string with list of tables.

    Examples:
        - db_list_tables()
        - db_list_tables("cnpj_raw")
    """
    return await list_tables(schema)


@mcp.tool()
async def db_get_schema(table: str, schema: str = "public") -> str:
    """
    Get detailed schema information for a table.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "public")

    Returns:
        JSON string with column details.

    Examples:
        - db_get_schema("empresas", "cnpj_raw")
        - db_get_schema("users")
    """
    return await get_schema(table, schema)


@mcp.tool()
async def db_get_indexes(table: str = None, schema: str = "cnpj_raw") -> str:
    """
    List indexes for a table or entire schema.

    Args:
        table: Optional table name to filter indexes
        schema: Schema name (default: "cnpj_raw")

    Returns:
        JSON string with index details.

    Examples:
        - db_get_indexes()
        - db_get_indexes("empresas")
    """
    return await get_indexes(table, schema)


@mcp.tool()
async def db_get_stats(table: str, schema: str = "cnpj_raw") -> str:
    """
    Get detailed statistics for a table.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "cnpj_raw")

    Returns:
        JSON string with statistics including row count, size, and maintenance info.

    Examples:
        - db_get_stats("empresas")
        - db_get_stats("estabelecimentos")
    """
    return await get_stats(table, schema)


@mcp.tool()
async def db_explain(sql: str, analyze: bool = True) -> str:
    """
    Run EXPLAIN ANALYZE on a query to see execution plan.

    Args:
        sql: The SQL query to analyze
        analyze: Whether to execute the query (default: True)

    Returns:
        JSON string with query plan and timing info.

    Examples:
        - db_explain("SELECT * FROM cnpj_raw.empresas WHERE razao_social ILIKE '%petrobras%'")
    """
    return await explain_query(sql, analyze)


@mcp.tool()
async def db_get_sample(table: str, schema: str = "public", limit: int = 10) -> str:
    """
    Get sample rows from a table.

    Args:
        table: Table name (without schema prefix)
        schema: Schema name (default: "public")
        limit: Number of rows (default: 10, max: 100)

    Returns:
        JSON string with sample rows.

    Examples:
        - db_get_sample("empresas", "cnpj_raw")
        - db_get_sample("users", limit=5)
    """
    return await get_sample(table, schema, limit)


@mcp.tool()
async def db_health() -> str:
    """
    Check database connection health.

    Returns:
        JSON string with connection status.
    """
    try:
        is_healthy = check_connection()
        return json.dumps({
            "success": True,
            "status": "healthy" if is_healthy else "unhealthy",
            "database_connected": is_healthy
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "status": "error",
            "error": str(e)
        })


def run_http_server():
    """Run MCP server with HTTP/SSE transport for Cloud Run."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse
    from mcp.server.sse import SseServerTransport

    # Create SSE transport with the messages path
    sse = SseServerTransport("/messages/")

    async def handle_sse(scope, receive, send):
        """Handle SSE connections."""
        logger.info("SSE connection started")
        async with sse.connect_sse(scope, receive, send) as streams:
            await mcp._mcp_server.run(
                streams[0], streams[1], mcp._mcp_server.create_initialization_options()
            )
        logger.info("SSE connection ended")

    async def handle_messages(scope, receive, send):
        """Handle message posting."""
        logger.info("Message received")
        await sse.handle_post_message(scope, receive, send)

    async def health(request):
        """Health check endpoint."""
        is_healthy = check_connection()
        return JSONResponse({
            "status": "healthy" if is_healthy else "unhealthy",
            "database": "connected" if is_healthy else "disconnected",
            "version": "1.0.0"
        })

    # Build a pure ASGI app that handles all routes
    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            # Handle lifespan events
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return

        if scope["type"] != "http":
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        if path == "/sse" and method == "GET":
            await handle_sse(scope, receive, send)
        elif path.startswith("/messages/") and method == "POST":
            await handle_messages(scope, receive, send)
        elif path in ["/", "/health"] and method == "GET":
            # Use Starlette for simple JSON responses
            from starlette.requests import Request
            request = Request(scope, receive, send)
            response = await health(request)
            await response(scope, receive, send)
        else:
            # 404 for unknown routes
            response_body = b'{"error": "Not found"}'
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })

    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting HTTP server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main():
    """Run the MCP server."""
    logger.info("Starting claude-db-tools MCP server...")

    try:
        # Initialize database pool
        init_pool()
        logger.info("Database pool initialized")

        # Check transport mode
        transport = os.environ.get("MCP_TRANSPORT", "stdio")

        if transport == "http":
            # HTTP/SSE transport for Cloud Run deployment
            logger.info("Running with HTTP/SSE transport")
            run_http_server()
        else:
            # Default: stdio transport for local development
            logger.info("Running with stdio transport")
            mcp.run(transport="stdio")

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        close_pool()
        logger.info("claude-db-tools stopped")


if __name__ == "__main__":
    main()
