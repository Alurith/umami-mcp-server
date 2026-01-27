from __future__ import annotations

import asyncio

import httpx
import pytest

from umami_mcp_server.settings import Settings
from umami_mcp_server.umami_client import UmamiClient


def _patch_async_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transport: httpx.MockTransport,
) -> None:
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def _no_sleep(_: float, result: object | None = None) -> object | None:
    return result


@pytest.mark.asyncio
async def test_login_flow_adds_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "t"
    seen_auth: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_auth

        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": token, "user": {"id": "1"}})

        if request.url.path.endswith("/websites"):
            seen_auth = request.headers.get("Authorization")
            return httpx.Response(
                200,
                json={"data": [], "count": 0, "page": 1, "pageSize": 10},
            )

        return httpx.Response(404, json={"error": "not found"})

    _patch_async_client(monkeypatch, transport=httpx.MockTransport(handler))

    settings = Settings(
        umami_username="u",
        umami_password="p",
        umami_api_base="https://example.com/api",
    )

    client = UmamiClient(settings)
    try:
        await client.get_websites()
    finally:
        await client.aclose()

    assert seen_auth == f"Bearer {token}"


@pytest.mark.asyncio
async def test_request_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.url.path.endswith("/websites")

        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    settings = Settings(
        umami_api_key="k",
        umami_api_base="https://api.umami.is/v1",
    )
    client = UmamiClient(settings)
    try:
        resp = await client.get_websites()
    finally:
        await client.aclose()

    assert resp == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_request_retries_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.url.path.endswith("/websites")

        calls += 1
        if calls == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    settings = Settings(
        umami_api_key="k",
        umami_api_base="https://api.umami.is/v1",
    )
    client = UmamiClient(settings)
    try:
        resp = await client.get_websites()
    finally:
        await client.aclose()

    assert resp == {"ok": True}
    assert calls == 2
