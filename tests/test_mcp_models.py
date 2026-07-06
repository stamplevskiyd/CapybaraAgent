"""Tests for the MCP ORM models' table shape."""

from capybara.db.base import Base
from capybara.db.models import McpServer, McpTool


def test_mcp_tables_registered_with_expected_columns() -> None:
    """Both MCP tables are on the metadata with their key columns."""
    tables = Base.metadata.tables
    assert "mcp_servers" in tables
    assert "mcp_tools" in tables

    server_cols = set(tables["mcp_servers"].columns.keys())
    assert {
        "id",
        "user_id",
        "name",
        "url",
        "headers",
        "enabled",
        "last_connected_at",
        "last_error",
        "created_at",
        "updated_at",
    } <= server_cols

    tool_cols = set(tables["mcp_tools"].columns.keys())
    assert {
        "id",
        "server_id",
        "name",
        "description",
        "input_schema",
        "enabled",
        "created_at",
        "updated_at",
    } <= tool_cols


def test_mcp_tool_has_unique_server_name() -> None:
    """A (server_id, name) uniqueness constraint prevents duplicate tools per server."""
    uniques = {
        tuple(c.name for c in con.columns)
        for con in McpTool.__table__.constraints
        if con.__class__.__name__ == "UniqueConstraint"
    }
    assert ("server_id", "name") in uniques
    assert McpServer.__tablename__ == "mcp_servers"
