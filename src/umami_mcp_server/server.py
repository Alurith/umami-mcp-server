from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from mcp.server import CacheHint, MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.shared.exceptions import MCPError
from mcp_types import TextContent
from pydantic import BaseModel, Field, ValidationError

from .models import (
    ActiveVisitors,
    Comparison,
    ExpandedMetric,
    Filters,
    IanaTimezone,
    Metric,
    MetricLimit,
    MetricOffset,
    MetricType,
    Page,
    PageSize,
    Pageviews,
    TimeUnit,
    WebsiteId,
    WebsitePage,
    WebsiteStats,
    ms_timerange,
)
from .settings import Settings
from .umami_client import UmamiClient

try:
    SERVER_VERSION = version("umami-mcp-server")
except PackageNotFoundError:
    SERVER_VERSION = "0.0.0"


@asynccontextmanager
async def _lifespan(_server: MCPServer[UmamiClient]) -> AsyncIterator[UmamiClient]:
    client = UmamiClient(Settings())
    try:
        yield client
    finally:
        await client.aclose()


async def _sanitize_validation_errors(
    ctx: ServerRequestContext[Any, Any],
    call_next: CallNext,
) -> HandlerResult:
    try:
        result = await call_next(ctx)
    except ValidationError:
        raise MCPError(-32602, "Invalid request parameters.") from None

    if isinstance(result, BaseModel):
        is_error = bool(getattr(result, "is_error", False))
        content = getattr(result, "content", [])
    elif isinstance(result, dict):
        is_error = bool(result.get("isError", result.get("is_error", False)))
        content = result.get("content", [])
    else:
        return result

    has_validation_details = is_error and any(
        "validation error"
        in (item.text if isinstance(item, TextContent) else str(item.get("text", ""))).lower()
        for item in content
        if isinstance(item, (TextContent, dict))
    )
    if not has_validation_details:
        return result

    safe_content = [TextContent(text="Invalid tool input.")]
    if isinstance(result, BaseModel):
        return result.model_copy(update={"content": safe_content})
    return {**result, "content": [item.model_dump(by_alias=True) for item in safe_content]}


server = MCPServer[UmamiClient](
    "umami-mcp-server",
    title="Umami MCP",
    version=SERVER_VERSION,
    lifespan=_lifespan,
    middleware=[_sanitize_validation_errors],
    cache_hints={
        "tools/list": CacheHint(
            ttl_ms=300_000,
            scope="public",
        ),
    },
)


def _filters_to_params(filters: Filters | None) -> dict[str, object]:
    return (
        filters.model_dump(mode="json", by_alias=True, exclude_none=True)
        if filters is not None
        else {}
    )


def _timerange_to_params(start_at: datetime | None, end_at: datetime | None) -> dict[str, int]:
    start_ms, end_ms = ms_timerange(start_at, end_at)
    return {"startAt": start_ms, "endAt": end_ms}


def _client(ctx: Context[UmamiClient]) -> UmamiClient:
    return ctx.request_context.lifespan_context


StartAt = Annotated[
    datetime | None,
    Field(
        description=(
            "Range start as an ISO datetime. Naive values are UTC. With no end, the range "
            "ends now; when omitted, the start is seven days before the selected end."
        )
    ),
]
EndAt = Annotated[
    datetime | None,
    Field(
        description=(
            "Range end as an ISO datetime. Naive values are UTC. With no start, the range "
            "covers the preceding seven days; when omitted, the end is now."
        )
    ),
]
ToolFilters = Annotated[
    Filters | None,
    Field(description="Optional documented Umami v3 filters."),
]


@server.tool()
async def get_websites(
    ctx: Context[UmamiClient],
    include_teams: Annotated[
        bool,
        Field(description="Include websites owned through teams."),
    ] = False,
    search: Annotated[
        str | None,
        Field(description="Optional text used to search website names and domains."),
    ] = None,
    page: Page = 1,
    page_size: PageSize = 10,
) -> WebsitePage:
    """Return one paginated page of websites available to the authenticated user."""

    return await _client(ctx).get_websites(
        include_teams=include_teams,
        search=search,
        page=page,
        page_size=page_size,
    )


@server.tool()
async def get_stats(
    ctx: Context[UmamiClient],
    website_id: WebsiteId,
    start_at: StartAt = None,
    end_at: EndAt = None,
    filters: ToolFilters = None,
) -> WebsiteStats:
    """Get summary statistics.

    With no dates the range is the last seven days; with only an end it is the seven days
    before that end; with only a start it ends now; with both dates it is explicit.
    """

    params: dict[str, object] = {}
    params.update(_timerange_to_params(start_at, end_at))
    params.update(_filters_to_params(filters))
    return await _client(ctx).get_stats(website_id, params=params)


@server.tool()
async def get_pageviews(
    ctx: Context[UmamiClient],
    website_id: WebsiteId,
    start_at: StartAt = None,
    end_at: EndAt = None,
    unit: TimeUnit = "day",
    timezone: IanaTimezone = "UTC",
    compare: Comparison = None,
    filters: ToolFilters = None,
) -> Pageviews:
    """Get pageviews over time.

    With no dates the range is the last seven days; with only an end it is the seven days
    before that end; with only a start it ends now; with both dates it is explicit.
    """

    query: dict[str, object] = {}
    query.update(_timerange_to_params(start_at, end_at))
    query.update({"unit": unit, "timezone": timezone})
    if compare is not None:
        query["compare"] = compare
    query.update(_filters_to_params(filters))
    return await _client(ctx).get_pageviews(website_id, params=query)


@server.tool()
async def get_metrics(
    ctx: Context[UmamiClient],
    website_id: WebsiteId,
    type: MetricType,
    start_at: StartAt = None,
    end_at: EndAt = None,
    limit: MetricLimit = 500,
    offset: MetricOffset = 0,
    expanded: Annotated[
        bool,
        Field(description="Return the expanded per-value statistics."),
    ] = False,
    filters: ToolFilters = None,
) -> list[Metric | ExpandedMetric]:
    """Get aggregated metrics.

    With no dates the range is the last seven days; with only an end it is the seven days
    before that end; with only a start it ends now; with both dates it is explicit.
    """

    query: dict[str, object] = {}
    query.update(_timerange_to_params(start_at, end_at))
    query.update({"type": type, "limit": limit, "offset": offset})
    query.update(_filters_to_params(filters))
    return await _client(ctx).get_metrics(website_id, expanded=expanded, params=query)


@server.tool()
async def get_active(ctx: Context[UmamiClient], website_id: WebsiteId) -> ActiveVisitors:
    """Return the number of visitors active during Umami's current active window."""

    return await _client(ctx).get_active(website_id)


def run() -> None:
    server.run()
