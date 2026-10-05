"""
claude-db-tools

REST API for PostgreSQL access - Claude Code sessions use it to query the Cloud SQL databases.

Usage:
    python -m src.server
"""
import logging
import sys
import os
import json

from .database import init_pool, close_pool, check_connection
from .tools.query import query, execute, count
from .tools.schema import list_tables, get_schema, get_indexes
from .tools.stats import get_stats, explain_query
from .tools.sample import get_sample

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def run_http_server():
    """Serve the REST API over HTTP (Cloud Run)."""
    import uvicorn
    from starlette.responses import JSONResponse
    from urllib.parse import parse_qs

    async def health(request):
        """Health check endpoint."""
        is_healthy = check_connection()
        return JSONResponse({
            "status": "healthy" if is_healthy else "unhealthy",
            "database": "connected" if is_healthy else "disconnected",
            "version": "1.0.0"
        })

    # REST API helper functions
    async def read_json_body(receive):
        """Read and parse JSON body from request."""
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        if body:
            return json.loads(body.decode("utf-8"))
        return {}

    async def send_json_response(send, data, status=200):
        """Send a JSON response."""
        body = json.dumps(data).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"access-control-allow-origin", b"*"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    async def handle_api_tables(scope, receive, send):
        """GET /api/tables?schema=cnpj_raw - List tables in a schema."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        schema = params.get("schema", ["public"])[0]
        try:
            result = await list_tables(schema)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_query(scope, receive, send):
        """POST /api/query - Execute a SELECT query."""
        try:
            body = await read_json_body(receive)
            sql = body.get("sql", "")
            limit = body.get("limit", 1000)
            if not sql:
                await send_json_response(send, {"error": "sql is required"}, 400)
                return
            result = await query(sql, limit)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_execute(scope, receive, send):
        """POST /api/execute - Execute a write operation."""
        try:
            body = await read_json_body(receive)
            sql = body.get("sql", "")
            allow_mojibake = bool(body.get("allow_mojibake", False))
            if not sql:
                await send_json_response(send, {"error": "sql is required"}, 400)
                return
            result = await execute(sql, allow_mojibake)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_count(scope, receive, send):
        """GET /api/count?table=schema.table&where=condition - Count rows."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        table = params.get("table", [None])[0]
        where = params.get("where", [None])[0]
        if not table:
            await send_json_response(send, {"error": "table is required"}, 400)
            return
        try:
            result = await count(table, where)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_schema(scope, receive, send):
        """GET /api/schema?table=name&schema=cnpj_raw - Get table schema."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        table = params.get("table", [None])[0]
        schema_name = params.get("schema", ["public"])[0]
        if not table:
            await send_json_response(send, {"error": "table is required"}, 400)
            return
        try:
            result = await get_schema(table, schema_name)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_indexes(scope, receive, send):
        """GET /api/indexes?table=name&schema=cnpj_raw - Get indexes."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        table = params.get("table", [None])[0]
        schema_name = params.get("schema", ["cnpj_raw"])[0]
        try:
            result = await get_indexes(table, schema_name)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_stats(scope, receive, send):
        """GET /api/stats?table=name&schema=cnpj_raw - Get table stats."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        table = params.get("table", [None])[0]
        schema_name = params.get("schema", ["cnpj_raw"])[0]
        if not table:
            await send_json_response(send, {"error": "table is required"}, 400)
            return
        try:
            result = await get_stats(table, schema_name)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_sample(scope, receive, send):
        """GET /api/sample?table=name&schema=cnpj_raw&limit=10 - Get sample rows."""
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        table = params.get("table", [None])[0]
        schema_name = params.get("schema", ["public"])[0]
        limit = int(params.get("limit", [10])[0])
        if not table:
            await send_json_response(send, {"error": "table is required"}, 400)
            return
        try:
            result = await get_sample(table, schema_name, limit)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

    async def handle_api_explain(scope, receive, send):
        """POST /api/explain - Explain a query."""
        try:
            body = await read_json_body(receive)
            sql = body.get("sql", "")
            analyze = body.get("analyze", True)
            if not sql:
                await send_json_response(send, {"error": "sql is required"}, 400)
                return
            result = await explain_query(sql, analyze)
            await send_json_response(send, json.loads(result))
        except Exception as e:
            await send_json_response(send, {"error": str(e)}, 500)

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

        # Health check
        if path in ["/", "/health"] and method == "GET":
            from starlette.requests import Request
            request = Request(scope, receive, send)
            response = await health(request)
            await response(scope, receive, send)
        # REST API routes
        elif path == "/api/tables" and method == "GET":
            await handle_api_tables(scope, receive, send)
        elif path == "/api/query" and method == "POST":
            await handle_api_query(scope, receive, send)
        elif path == "/api/execute" and method == "POST":
            await handle_api_execute(scope, receive, send)
        elif path == "/api/count" and method == "GET":
            await handle_api_count(scope, receive, send)
        elif path == "/api/schema" and method == "GET":
            await handle_api_schema(scope, receive, send)
        elif path == "/api/indexes" and method == "GET":
            await handle_api_indexes(scope, receive, send)
        elif path == "/api/stats" and method == "GET":
            await handle_api_stats(scope, receive, send)
        elif path == "/api/sample" and method == "GET":
            await handle_api_sample(scope, receive, send)
        elif path == "/api/explain" and method == "POST":
            await handle_api_explain(scope, receive, send)
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
    """Run the REST API server."""
    logger.info("Starting claude-db-tools...")

    try:
        # Initialize database pool
        init_pool()
        logger.info("Database pool initialized")

        run_http_server()

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
