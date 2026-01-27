from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .models import Filters, ms_timerange
from .settings import get_settings
from .umami_client import UmamiClient

server = FastMCP("Umami MCP")


@asynccontextmanager
async def _umami_client() -> AsyncIterator[UmamiClient]:
    client = UmamiClient(get_settings())
    try:
        yield client
    finally:
        await client.aclose()


def _filters_to_params(filters: Filters | None) -> dict[str, Any]:
    return filters.model_dump(exclude_none=True) if filters is not None else {}


def _timerange_to_params(start_at: datetime | None, end_at: datetime | None) -> dict[str, Any]:
    start_ms, end_ms = ms_timerange(start_at, end_at)
    return {"startAt": start_ms, "endAt": end_ms}


@server.tool()
async def get_websites(
    include_teams: bool = False,
    search: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """List all your websites."""

    async with _umami_client() as client:
        return await client.get_websites(
            include_teams=include_teams,
            search=search,
            page=page,
            page_size=page_size,
        )


@server.tool()
async def get_stats(
    website_id: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    filters: Filters | None = None,
) -> dict[str, Any]:
    """Get visitor statistics."""

    params: dict[str, Any] = {}
    params.update(_timerange_to_params(start_at, end_at))
    params.update(_filters_to_params(filters))

    async with _umami_client() as client:
        return await client.get_stats(website_id, params=params)


@server.tool()
async def get_pageviews(
    website_id: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    unit: Literal["hour", "day", "month", "year"] = "day",
    timezone: str = "UTC",
    compare: Literal["prev", "yoy"] | None = None,
    filters: Filters | None = None,
) -> dict[str, Any]:
    """View page traffic over time."""

    query: dict[str, Any] = {}
    query.update(_timerange_to_params(start_at, end_at))
    query.update({"unit": unit, "timezone": timezone})
    if compare is not None:
        query["compare"] = compare
    query.update(_filters_to_params(filters))

    async with _umami_client() as client:
        return await client.get_pageviews(website_id, params=query)


@server.tool()
async def get_metrics(
    website_id: str,
    type: str,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = 500,
    offset: int = 0,
    expanded: bool = False,
    filters: Filters | None = None,
) -> list[dict[str, Any]]:
    """See browsers, countries, devices, and more."""

    query: dict[str, Any] = {}
    query.update(_timerange_to_params(start_at, end_at))
    query.update({"type": type, "limit": limit, "offset": offset})
    query.update(_filters_to_params(filters))

    async with _umami_client() as client:
        return await client.get_metrics(website_id, expanded=expanded, params=query)


@server.tool()
async def get_active(website_id: str) -> dict[str, Any]:
    """Current active visitors."""

    async with _umami_client() as client:
        return await client.get_active(website_id)


def run() -> None:
    # Validate configuration early so failures are obvious.
    get_settings()
    server.run()
