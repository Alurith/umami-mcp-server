from __future__ import annotations

from collections.abc import Iterator

import pytest

from umami_mcp_server.settings import get_settings


@pytest.fixture(autouse=True)
def _isolate_umami_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "UMAMI_API_KEY",
        "UMAMI_USERNAME",
        "UMAMI_PASSWORD",
        "UMAMI_API_BASE",
        "UMAMI_LIVE_CLOUD_API_KEY",
        "UMAMI_LIVE_CLOUD_WEBSITE_ID",
        "UMAMI_LIVE_CLOUD_API_BASE",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
