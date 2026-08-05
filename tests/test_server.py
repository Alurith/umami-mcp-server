from __future__ import annotations

import pytest
from mcp.client import Client

from umami_mcp_server.server import SERVER_VERSION, server


@pytest.mark.asyncio
async def test_server_negotiates_current_protocol() -> None:
    async with Client(server, raise_exceptions=True) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_info is not None
        assert client.server_info.name == "umami-mcp-server"
        assert client.server_info.title == "Umami MCP"
        assert client.server_info.version == SERVER_VERSION


@pytest.mark.asyncio
async def test_server_lists_tools_in_deterministic_order() -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools(cache_mode="bypass")

    assert [tool.name for tool in result.tools] == [
        "get_websites",
        "get_stats",
        "get_pageviews",
        "get_metrics",
        "get_active",
    ]
    assert result.result_type == "complete"


@pytest.mark.asyncio
async def test_server_exposes_input_and_output_schemas() -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools(cache_mode="bypass")

    tools = {tool.name: tool for tool in result.tools}

    assert tools["get_websites"].input_schema["type"] == "object"
    assert tools["get_stats"].input_schema["required"] == ["website_id"]
    assert tools["get_pageviews"].input_schema["properties"]["unit"]["enum"] == [
        "hour",
        "day",
        "month",
        "year",
    ]
    assert tools["get_metrics"].input_schema["required"] == ["website_id", "type"]
    assert tools["get_active"].input_schema["required"] == ["website_id"]
    assert all(tool.output_schema is not None for tool in result.tools)


@pytest.mark.asyncio
async def test_server_keeps_legacy_client_compatibility() -> None:
    async with Client(server, mode="legacy") as legacy_client:
        result = await legacy_client.list_tools(cache_mode="bypass")

    assert [tool.name for tool in result.tools] == [
        "get_websites",
        "get_stats",
        "get_pageviews",
        "get_metrics",
        "get_active",
    ]
