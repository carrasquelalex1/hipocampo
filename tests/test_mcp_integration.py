"""Integration tests for the Hipocampo MCP server.

Tests are split into two categories:

1. **Schema tests** (no DB required) — verify tool registration, annotations,
   argument definitions, resource endpoints.
2. **Live server tests** (DB required, marked ``integration``) — start the
   server in a subprocess (stdio) and call tools via the MCP client.

Run all tests:
    pytest tests/test_mcp_integration.py

Run only schema tests (skips DB-dependent):
    pytest tests/test_mcp_integration.py -m "not integration"

Run only live tests:
    pytest tests/test_mcp_integration.py -m integration
"""

import asyncio
import os
import sys
import logging

# Suppress server-side logging during schema tests
logging.disable(logging.CRITICAL)

SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")

# ─── TOOL INVENTORY ──────────────────────────────────────────────────────────
EXPECTED_TOOLS = {
    "search_hipocampo",
    "quick_hipocampo_search",
    "compress_hipocampo",
    "save_hipocampo",
    "profile_hipocampo",
    "update_hipocampo",
    "delete_hipocampo",
    "hipocampo_health",
    "hipocampo_auto_repair",
    "hipocampo_stats",
    "hipocampo_tune",
    "hipocampo_dedup",
    "hipocampo_checkpoint",
    "hipocampo_maintenance",
    "watch_hipocampo",
    "unwatch_hipocampo",
    "list_watches",
}

TOOLS_WITH_SESSION_ID = {"search_hipocampo", "quick_hipocampo_search", "save_hipocampo"}

TOOLS_READ_ONLY = {
    "search_hipocampo",
    "quick_hipocampo_search",
    "compress_hipocampo",
    "hipocampo_health",
    "hipocampo_stats",
    "list_watches",
}

TOOLS_DESTRUCTIVE = {
    "update_hipocampo",
    "delete_hipocampo",
    "hipocampo_tune",
    "hipocampo_dedup",
    "hipocampo_checkpoint",
}

TOOLS_WITH_REQUIRED = {
    "search_hipocampo": ["query"],
    "compress_hipocampo": ["query"],
    "save_hipocampo": ["content"],
    "delete_hipocampo": ["id"],
    "update_hipocampo": ["id"],
    "profile_hipocampo": ["summary"],
    "watch_hipocampo": ["pattern", "webhook_url"],
    "unwatch_hipocampo": ["id"],
}


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _get_server_module():
    """Import and return the MCP server module."""
    orig_path = list(sys.path)
    sys.path.insert(0, SERVER_DIR)
    sys.path.insert(0, os.path.dirname(SERVER_DIR))
    try:
        import hipocampo_mcp_server as mod

        return mod
    finally:
        sys.path = orig_path


def _tools_map():
    """Return {name: Tool} dict from the FastMCP instance."""
    mod = _get_server_module()
    tools = mod.mcp._tool_manager.list_tools()
    return {t.name: t for t in tools}


# ─── SCHEMA TESTS (NO DB) ─────────────────────────────────────────────────────


def test_all_tools_registered():
    """All 16 tools must be registered on the FastMCP instance."""
    mod = _get_server_module()
    tools = mod.mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}
    missing = EXPECTED_TOOLS - tool_names
    extra = tool_names - EXPECTED_TOOLS
    assert not missing, f"Faltan herramientas: {missing}"
    assert not extra, f"Herramientas extra no esperadas: {extra}"
    assert len(tools) == 17


def test_tool_annotations():
    """readOnlyHint and destructiveHint are correctly assigned (if supported by FastMCP version)."""
    tools = _tools_map()
    for name, t in tools.items():
        if t.annotations is None:
            continue
        if name in TOOLS_READ_ONLY:
            assert t.annotations.readOnlyHint, (
                f"{name} debería tener readOnlyHint=True, tiene annotations={t.annotations}"
            )
        if name in TOOLS_DESTRUCTIVE:
            assert t.annotations.destructiveHint, (
                f"{name} debería tener destructiveHint=True, tiene annotations={t.annotations}"
            )


def test_session_id_parameter():
    """Tools that accept session_id must have it in their schema."""
    tools = _tools_map()
    for name in TOOLS_WITH_SESSION_ID:
        t = tools[name]
        props = t.parameters.get("properties", {})
        assert "session_id" in props, f"{name} debería tener parámetro 'session_id', tiene: {list(props.keys())}"


def test_required_parameters():
    """Tool parameters with required=True are correctly set."""
    tools = _tools_map()
    for name, expected_required in TOOLS_WITH_REQUIRED.items():
        t = tools[name]
        required = t.parameters.get("required", [])
        for param in expected_required:
            assert param in required, f"{name} debería requerir '{param}', required={required}"


def test_resource_info():
    """The hipocampo://info resource must be registered."""
    mod = _get_server_module()
    resources = asyncio.run(mod.mcp.list_resources())
    uris = [str(r.uri) for r in resources]
    assert "hipocampo://info" in uris


def test_all_tools_async():
    """All tools should be async functions for non-blocking HTTP mode."""
    tools = _tools_map()
    for name, t in tools.items():
        assert t.is_async, f"{name} debería ser async"


# ─── LIVE SERVER TESTS (DB REQUIRED) ─────────────────────────────────────────

import pytest

skip_no_db = pytest.mark.skipif(
    "CI" in os.environ,
    reason="DB no disponible en CI",
)


@skip_no_db
@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_stdio_hipocampo_info():
    """Start the server via stdio_client and read the info resource."""
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=[os.path.join(SERVER_DIR, "hipocampo_mcp_server.py")])
    async with stdio_client(params) as (read, write):
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()
            resources = await session.list_resources()
            uris = [str(r.uri) for r in resources.resources]
            assert "hipocampo://info" in uris


@skip_no_db
@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_stdio_tools_list():
    """Start the server via stdio_client and list tools."""
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=[os.path.join(SERVER_DIR, "hipocampo_mcp_server.py")])
    async with stdio_client(params) as (read, write):
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {t.name for t in tools.tools}
            assert tool_names == EXPECTED_TOOLS, (
                f"Mismatch: extra={tool_names - EXPECTED_TOOLS}, missing={EXPECTED_TOOLS - tool_names}"
            )


@skip_no_db
@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_stdio_search():
    """Start the server and call search_hipocampo."""
    from mcp.client.stdio import stdio_client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=[os.path.join(SERVER_DIR, "hipocampo_mcp_server.py")])
    async with stdio_client(params) as (read, write):
        from mcp import ClientSession

        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_hipocampo", {"query": "test"})
            text = "".join(c.text for c in result.content if hasattr(c, "text"))
            assert "❌" not in text, f"search returned error: {text}"
