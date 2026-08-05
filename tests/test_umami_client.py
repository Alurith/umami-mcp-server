from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, cast

import httpx
import pytest

from umami_mcp_server.models import WebsitePage
from umami_mcp_server.settings import Settings
from umami_mcp_server.umami_client import (
    UmamiAuthenticationError,
    UmamiClient,
    UmamiInvalidResponseError,
    UmamiNetworkError,
    UmamiRateLimitError,
    UmamiTimeoutError,
    UmamiUpstreamError,
)

WEBSITES = {"data": [], "count": 0, "page": 1, "pageSize": 10}
Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def _settings(*, login: bool = False) -> Settings:
    if login:
        return Settings(
            umami_username="synthetic-user",
            umami_password="synthetic-password",
            umami_api_base="https://self-hosted.example.invalid/api",
        )
    return Settings(
        umami_api_key="synthetic-api-key",
        umami_api_base="https://api.umami.is/v1",
    )


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(cast(Any, handler))

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return original(*args, **dict(kwargs), transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def _recording_sleep(delays: list[float], delay: float) -> object:
    delays.append(delay)
    return None


@pytest.mark.asyncio
async def test_login_flow_adds_bearer_token_and_returns_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_auth: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_auth
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "token-1"})
        seen_auth = request.headers.get("Authorization")
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        result = await client.get_websites()
    finally:
        await client.aclose()

    assert isinstance(result, WebsitePage)
    assert seen_auth == "Bearer token-1"


@pytest.mark.asyncio
async def test_concurrent_initial_requests_perform_one_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            await asyncio.sleep(0)
            return httpx.Response(200, json={"token": "shared-token"})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        await asyncio.gather(client.get_websites(), client.get_websites())
    finally:
        await client.aclose()

    assert login_calls == 1


@pytest.mark.asyncio
async def test_401_refreshes_token_and_resends_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_calls = 0
    analytics_calls = 0
    auth_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, analytics_calls
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            return httpx.Response(200, json={"token": f"token-{login_calls}"})
        analytics_calls += 1
        auth_headers.append(request.headers.get("Authorization"))
        if analytics_calls == 1:
            return httpx.Response(401, json={"secret": "must-not-leak"})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        await client.get_websites()
    finally:
        await client.aclose()

    assert login_calls == 2
    assert analytics_calls == 2
    assert auth_headers == ["Bearer token-1", "Bearer token-2"]


@pytest.mark.asyncio
async def test_concurrent_401_responses_perform_one_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_calls = 0
    stale_requests = 0
    both_stale_sent = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, stale_requests
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            return httpx.Response(200, json={"token": f"token-{login_calls}"})

        if request.headers.get("Authorization") == "Bearer token-1":
            stale_requests += 1
            if stale_requests == 2:
                both_stale_sent.set()
            await both_stale_sent.wait()
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        await asyncio.gather(client.get_websites(), client.get_websites())
    finally:
        await client.aclose()

    assert stale_requests == 2
    assert login_calls == 2


@pytest.mark.asyncio
async def test_second_401_does_not_refresh_again(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls = 0
    analytics_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, analytics_calls
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            return httpx.Response(200, json={"token": f"token-{login_calls}"})
        analytics_calls += 1
        return httpx.Response(401, json={"error": "expired"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        with pytest.raises(UmamiAuthenticationError):
            await client.get_websites()
    finally:
        await client.aclose()

    assert login_calls == 2
    assert analytics_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_api_key_auth_errors_are_not_retried(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"secret": "hidden"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings())
    try:
        with pytest.raises(UmamiAuthenticationError):
            await client.get_websites()
    finally:
        await client.aclose()
    assert calls == 1


@pytest.mark.asyncio
async def test_login_mode_403_does_not_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls = 0
    analytics_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, analytics_calls
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            return httpx.Response(200, json={"token": "token"})
        analytics_calls += 1
        return httpx.Response(403, json={"error": "forbidden"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        with pytest.raises(UmamiAuthenticationError):
            await client.get_websites()
    finally:
        await client.aclose()
    assert (login_calls, analytics_calls) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        ("network", UmamiNetworkError),
        ("timeout", UmamiTimeoutError),
        (429, UmamiRateLimitError),
        (500, UmamiUpstreamError),
        (502, UmamiUpstreamError),
        (503, UmamiUpstreamError),
        (504, UmamiUpstreamError),
    ],
)
async def test_retryable_failures_send_exactly_three_requests_and_sleep_twice(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | int,
    error_type: type[Exception],
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "network":
            raise httpx.ConnectError("sensitive transport detail", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("sensitive timeout detail", request=request)
        return httpx.Response(int(failure), json={"secret": "upstream-body"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(
        _settings(),
        _sleep=lambda delay: _recording_sleep(delays, delay),
        _random_uniform=lambda _low, high: high,
    )
    try:
        with pytest.raises(error_type):
            await client.get_websites()
    finally:
        await client.aclose()

    assert calls == 3
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 501, 505])
async def test_non_retryable_statuses_are_sent_once(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "no retry"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(), _sleep=lambda delay: _recording_sleep(delays, delay))
    try:
        with pytest.raises(UmamiUpstreamError):
            await client.get_websites()
    finally:
        await client.aclose()
    assert calls == 1
    assert delays == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_after", "clock", "expected_delay"),
    [
        ("12", datetime(2026, 1, 1, tzinfo=timezone.utc), 12.0),
        (
            format_datetime(datetime(2026, 1, 1, 0, 0, 20, tzinfo=timezone.utc), usegmt=True),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            20.0,
        ),
        ("120", datetime(2026, 1, 1, tzinfo=timezone.utc), 60.0),
        ("invalid", datetime(2026, 1, 1, tzinfo=timezone.utc), 0.5),
    ],
)
async def test_retry_after_parsing_precedence_fallback_and_cap(
    monkeypatch: pytest.MonkeyPatch,
    retry_after: str,
    clock: datetime,
    expected_delay: float,
) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": retry_after}, json={})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(
        _settings(),
        _sleep=lambda delay: _recording_sleep(delays, delay),
        _random_uniform=lambda _low, high: high,
        _clock=lambda: clock,
    )
    try:
        await client.get_websites()
    finally:
        await client.aclose()
    assert delays == [expected_delay]


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_json", [True, False])
async def test_malformed_json_and_invalid_payload_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    malformed_json: bool,
) -> None:
    calls = 0
    response = (
        httpx.Response(200, content=b"not-json", headers={"Content-Type": "application/json"})
        if malformed_json
        else httpx.Response(200, json={"unexpected": "shape"})
    )

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings())
    try:
        with pytest.raises(UmamiInvalidResponseError, match="invalid response"):
            await client.get_websites()
    finally:
        await client.aclose()
    assert calls == 1
    assert response.is_closed


@pytest.mark.asyncio
async def test_invalid_login_token_is_a_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": 123, "password": "sensitive"})

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        with pytest.raises(UmamiInvalidResponseError, match="invalid login response"):
            await client.get_websites()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_errors_and_logs_do_not_expose_secrets_or_upstream_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_values = [
        "synthetic-api-key",
        "synthetic-password",
        "private-upstream-body",
        "sensitive-query-value",
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"detail": "private-upstream-body", "token": "synthetic-api-key"},
        )

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(), _sleep=lambda _delay: asyncio.sleep(0))
    caplog.set_level(logging.DEBUG)
    try:
        with pytest.raises(UmamiUpstreamError) as caught:
            await client.get_websites(search="sensitive-query-value")
    finally:
        await client.aclose()

    public_text = str(caught.value)
    log_text = caplog.text
    for secret in secret_values:
        assert secret not in public_text
        assert secret not in log_text
    assert "endpoint=/websites" in log_text
    assert "status=500" in log_text


@pytest.mark.asyncio
async def test_response_and_async_client_are_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(200, json=WEBSITES)

    def handler(_: httpx.Request) -> httpx.Response:
        return response

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings())
    await client.get_websites()
    assert response.is_closed
    assert not client._client.is_closed
    await client.aclose()
    assert client._client.is_closed
