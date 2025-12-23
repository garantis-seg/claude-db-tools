"""
Tests for MCP tools

Note: These tests require a database connection.
Set environment variables before running:
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import pytest
import json
import os

# Skip all tests if DB_PASSWORD not set
pytestmark = pytest.mark.skipif(
    not os.environ.get("DB_PASSWORD"),
    reason="DB_PASSWORD not set - skipping database tests"
)


class TestQueryTools:
    """Tests for query tools"""

    @pytest.mark.asyncio
    async def test_query_select(self):
        """Test basic SELECT query"""
        from src.tools.query import query

        result = await query("SELECT 1 as test")
        data = json.loads(result)

        assert data["success"] is True
        assert data["rows"] == 1
        assert data["data"][0]["test"] == 1

    @pytest.mark.asyncio
    async def test_query_rejects_insert(self):
        """Test that INSERT is rejected"""
        from src.tools.query import query

        result = await query("INSERT INTO test VALUES (1)")
        data = json.loads(result)

        assert data["success"] is False
        assert "SELECT" in data["error"]

    @pytest.mark.asyncio
    async def test_count(self):
        """Test count tool"""
        from src.tools.query import count

        result = await count("pg_tables")
        data = json.loads(result)

        assert data["success"] is True
        assert data["count"] > 0


class TestSchemaTools:
    """Tests for schema tools"""

    @pytest.mark.asyncio
    async def test_list_tables(self):
        """Test listing tables"""
        from src.tools.schema import list_tables

        result = await list_tables("pg_catalog")
        data = json.loads(result)

        assert data["success"] is True
        assert data["total_tables"] > 0

    @pytest.mark.asyncio
    async def test_get_schema(self):
        """Test getting table schema"""
        from src.tools.schema import get_schema

        result = await get_schema("pg_tables", "pg_catalog")
        data = json.loads(result)

        assert data["success"] is True
        assert len(data["columns"]) > 0


class TestSampleTools:
    """Tests for sample tools"""

    @pytest.mark.asyncio
    async def test_get_sample(self):
        """Test getting sample rows"""
        from src.tools.sample import get_sample

        result = await get_sample("pg_tables", "pg_catalog", 5)
        data = json.loads(result)

        assert data["success"] is True
        assert data["rows_returned"] <= 5

    @pytest.mark.asyncio
    async def test_get_sample_not_found(self):
        """Test sample from non-existent table"""
        from src.tools.sample import get_sample

        result = await get_sample("nonexistent_table_xyz")
        data = json.loads(result)

        assert data["success"] is False
        assert "not found" in data["error"]
