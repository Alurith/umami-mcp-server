from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from umami_mcp_server.models import datetime_to_ms
from umami_mcp_server.settings import Settings
from umami_mcp_server.umami_client import UmamiClient

_API_KEY = os.getenv("UMAMI_LIVE_CLOUD_API_KEY")
_WEBSITE_ID = os.getenv("UMAMI_LIVE_CLOUD_WEBSITE_ID")
_API_BASE = os.getenv("UMAMI_LIVE_CLOUD_API_BASE", "https://api.umami.is/v1")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (_API_KEY and _WEBSITE_ID),
        reason="live Cloud credentials were not provided",
    ),
]


async def test_live_cloud_read_only_contract() -> None:
    assert _API_KEY is not None
    assert _WEBSITE_ID is not None
    website_id = UUID(_WEBSITE_ID)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    range_params = {"startAt": datetime_to_ms(start), "endAt": datetime_to_ms(end)}

    client = UmamiClient(
        Settings(umami_api_key=_API_KEY, umami_api_base=_API_BASE),
    )
    try:
        await client.get_websites(page=1, page_size=10)
        await client.get_stats(website_id, params=range_params)
        await client.get_pageviews(
            website_id,
            params={**range_params, "unit": "day", "timezone": "UTC"},
        )
        await client.get_metrics(
            website_id,
            expanded=False,
            params={**range_params, "type": "path", "limit": 10, "offset": 0},
        )
        await client.get_metrics(
            website_id,
            expanded=True,
            params={**range_params, "type": "path", "limit": 10, "offset": 0},
        )
        await client.get_active(website_id)
    finally:
        await client.aclose()
