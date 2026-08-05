from __future__ import annotations

import asyncio
import importlib
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from mcp.client import Client

from umami_mcp_server.models import (
    ActiveVisitors,
    ExpandedMetric,
    Metric,
    Pageviews,
    StatsValues,
    WebsitePage,
    WebsiteStats,
)
from umami_mcp_server.server import SERVER_VERSION, server
from umami_mcp_server.umami_client import UmamiUpstreamError

server_module = importlib.import_module("umami_mcp_server.server")
WEBSITE_ID = "11111111-1111-4111-8111-111111111111"
METRIC_TYPES = [
    "path",
    "fullPath",
    "entry",
    "exit",
    "referrer",
    "domain",
    "title",
    "query",
    "event",
    "tag",
    "hostname",
    "utmSource",
    "utmMedium",
    "utmCampaign",
    "utmContent",
    "utmTerm",
    "browser",
    "os",
    "device",
    "screen",
    "language",
    "country",
    "city",
    "region",
    "distinctId",
    "channel",
]


class FakeUmamiClient:
    instances: list["FakeUmamiClient"] = []
    fail_active = False

    def __init__(self, _settings: object) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.close_calls = 0
        self.instances.append(self)

    async def aclose(self) -> None:
        self.close_calls += 1

    async def get_websites(self, **kwargs: Any) -> WebsitePage:
        self.calls.append(("get_websites", kwargs))
        return WebsitePage.model_validate(
            {"data": [], "count": 0, "page": 1, "pageSize": 10, "fakeExtra": True}
        )

    async def get_stats(self, website_id: UUID, *, params: dict[str, Any]) -> WebsiteStats:
        self.calls.append(("get_stats", (website_id, params)))
        values = dict(pageviews=10, visitors=5, visits=6, bounces=2, totaltime=100)
        return WebsiteStats.model_validate(
            {**values, "comparison": StatsValues(**values), "fakeExtra": True}
        )

    async def get_pageviews(self, website_id: UUID, *, params: dict[str, Any]) -> Pageviews:
        self.calls.append(("get_pageviews", (website_id, params)))
        return Pageviews.model_validate({"pageviews": [], "sessions": [], "fakeExtra": True})

    async def get_metrics(
        self,
        website_id: UUID,
        *,
        expanded: bool,
        params: dict[str, Any],
    ) -> list[Metric | ExpandedMetric]:
        self.calls.append(("get_metrics", (website_id, expanded, params)))
        if expanded:
            return [
                ExpandedMetric(
                    name="Chrome",
                    pageviews=10,
                    visitors=5,
                    visits=6,
                    bounces=2,
                    totaltime=100,
                )
            ]
        return [Metric(x="Chrome", y=5)]

    async def get_active(self, website_id: UUID) -> ActiveVisitors:
        self.calls.append(("get_active", website_id))
        if self.fail_active:
            raise UmamiUpstreamError("safe upstream failure")
        return ActiveVisitors.model_validate({"visitors": 1, "fakeExtra": True})


@pytest.fixture
def fake_lifespan(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[FakeUmamiClient]]:
    FakeUmamiClient.instances = []
    FakeUmamiClient.fail_active = False
    monkeypatch.setattr(server_module, "get_settings", lambda: object())
    monkeypatch.setattr(server_module, "UmamiClient", FakeUmamiClient)
    yield FakeUmamiClient


@pytest.mark.asyncio
async def test_server_negotiates_current_protocol(fake_lifespan: type[FakeUmamiClient]) -> None:
    async with Client(server, raise_exceptions=True) as client:
        assert client.protocol_version == "2026-07-28"
        assert client.server_info is not None
        assert client.server_info.name == "umami-mcp-server"
        assert client.server_info.title == "Umami MCP"
        assert client.server_info.version == SERVER_VERSION


@pytest.mark.asyncio
async def test_server_capabilities_match_the_standard_mcpserver_surface(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        capabilities = client.server_capabilities.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )

    assert capabilities == {
        "prompts": {"listChanged": True},
        "resources": {"subscribe": True, "listChanged": True},
        "tools": {"listChanged": True},
    }
    assert "logging" not in capabilities
    assert "tasks" not in capabilities
    assert "experimental" not in capabilities


@pytest.mark.asyncio
async def test_server_lists_tools_in_deterministic_order(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        first = await client.list_tools(cache_mode="bypass")
        second = await client.list_tools(cache_mode="bypass")

    assert [tool.name for tool in first.tools] == [
        "get_websites",
        "get_stats",
        "get_pageviews",
        "get_metrics",
        "get_active",
    ]
    assert first.result_type == "complete"
    assert first.model_dump(mode="json", by_alias=True) == second.model_dump(
        mode="json", by_alias=True
    )


@pytest.mark.asyncio
async def test_tools_catalog_has_a_public_five_minute_cache_hint(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools(cache_mode="bypass")

    assert result.ttl_ms == 300_000
    assert result.cache_scope == "public"


@pytest.mark.asyncio
async def test_server_exposes_strong_input_and_output_schemas(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.list_tools(cache_mode="bypass")

    tools = {tool.name: tool for tool in result.tools}
    for tool in tools.values():
        assert "ctx" not in tool.input_schema.get("properties", {})

    website_id = tools["get_stats"].input_schema["properties"]["website_id"]
    assert website_id["format"] == "uuid"
    assert tools["get_websites"].input_schema["properties"]["page"]["minimum"] == 1
    page_size = tools["get_websites"].input_schema["properties"]["page_size"]
    assert (page_size["minimum"], page_size["maximum"]) == (1, 100)
    assert tools["get_pageviews"].input_schema["properties"]["unit"]["enum"] == [
        "minute",
        "hour",
        "day",
        "month",
        "year",
    ]
    compare_schema = tools["get_pageviews"].input_schema["properties"]["compare"]
    assert "previous period" in compare_schema["description"]
    assert tools["get_metrics"].input_schema["properties"]["type"]["enum"] == METRIC_TYPES
    limit = tools["get_metrics"].input_schema["properties"]["limit"]
    offset = tools["get_metrics"].input_schema["properties"]["offset"]
    assert (limit["minimum"], limit["maximum"]) == (1, 500)
    assert (offset["minimum"], offset["maximum"]) == (0, 10_000)

    stats_output = tools["get_stats"].output_schema
    active_output = tools["get_active"].output_schema
    metrics_output = tools["get_metrics"].output_schema
    assert stats_output is not None
    assert active_output is not None
    assert metrics_output is not None
    assert stats_output["properties"]["pageviews"]["type"] == "integer"
    assert stats_output["additionalProperties"] is True
    assert active_output["additionalProperties"] is True
    assert metrics_output["properties"]["result"]["type"] == "array"
    assert metrics_output["$defs"]["Metric"]["additionalProperties"] is True


@pytest.mark.asyncio
async def test_one_client_is_reused_across_tools_and_closed_once(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("get_websites", {})
        await client.call_tool("get_active", {"website_id": WEBSITE_ID})
        assert len(fake_lifespan.instances) == 1
        instance = fake_lifespan.instances[0]
        assert [name for name, _ in instance.calls] == ["get_websites", "get_active"]
        assert instance.close_calls == 0

    assert instance.close_calls == 1


@pytest.mark.asyncio
async def test_lifespan_closes_client_after_tool_exception(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    fake_lifespan.fail_active = True
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_active", {"website_id": WEBSITE_ID})
        assert result.is_error is True

    assert len(fake_lifespan.instances) == 1
    assert fake_lifespan.instances[0].close_calls == 1


@pytest.mark.asyncio
async def test_concurrent_tool_calls_share_the_client(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        await asyncio.gather(
            client.call_tool("get_websites", {}),
            client.call_tool("get_active", {"website_id": WEBSITE_ID}),
        )

    assert len(fake_lifespan.instances) == 1
    assert len(fake_lifespan.instances[0].calls) == 2
    assert fake_lifespan.instances[0].close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_active", {"website_id": "not-a-uuid"}),
        ("get_websites", {"page": 0}),
        ("get_websites", {"page_size": 101}),
        ("get_pageviews", {"website_id": WEBSITE_ID, "timezone": "Mars/Olympus"}),
        ("get_metrics", {"website_id": WEBSITE_ID, "type": "unknown"}),
        ("get_metrics", {"website_id": WEBSITE_ID, "type": "path", "limit": 0}),
    ],
)
async def test_invalid_inputs_are_rejected_before_http(
    fake_lifespan: type[FakeUmamiClient], tool: str, arguments: dict[str, Any]
) -> None:
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(tool, arguments)
        assert result.is_error is True
        text = " ".join(getattr(item, "text", "") for item in result.content)
        assert text == "Invalid tool input."
        assert not any(str(value) in text for value in arguments.values())
        assert fake_lifespan.instances[0].calls == []


@pytest.mark.asyncio
async def test_upstream_error_is_a_sanitized_tool_error(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    fake_lifespan.fail_active = True
    async with Client(server) as client:
        result = await client.call_tool("get_active", {"website_id": WEBSITE_ID})

    assert result.is_error is True
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert "safe upstream failure" in text
    assert "Traceback" not in text


@pytest.mark.asyncio
async def test_server_keeps_legacy_client_compatibility(
    fake_lifespan: type[FakeUmamiClient],
) -> None:
    async with Client(server, mode="legacy") as legacy_client:
        result = await legacy_client.list_tools(cache_mode="bypass")

    assert [tool.name for tool in result.tools] == [
        "get_websites",
        "get_stats",
        "get_pageviews",
        "get_metrics",
        "get_active",
    ]
    assert "ttl_ms" not in result.model_fields_set
    assert "cache_scope" not in result.model_fields_set
