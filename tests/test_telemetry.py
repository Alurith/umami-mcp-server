from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from mcp.client import Client
from mcp_types import RequestParamsMeta
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan

from conftest import OtelCapture, WEBSITES, _patch_async_client, _settings
from umami_mcp_server import telemetry
from umami_mcp_server.server import server
from umami_mcp_server.umami_client import UmamiClient, UmamiRateLimitError, UmamiUpstreamError

TRACE_ID = "1234567890abcdef1234567890abcdef"
REMOTE_PARENT_ID = "1234567890abcdef"
ALLOWED_ATTRIBUTES = {
    telemetry.HTTP_REQUEST_METHOD,
    telemetry.HTTP_RESPONSE_STATUS_CODE,
    telemetry.UMAMI_ENDPOINT,
    telemetry.UMAMI_AUTH_MODE,
    telemetry.UMAMI_RETRY_COUNT,
    telemetry.UMAMI_OUTCOME,
    telemetry.UMAMI_RETRY_CAUSE,
    telemetry.ERROR_TYPE,
}


def _application_spans(capture: OtelCapture) -> list[ReadableSpan]:
    return [
        span
        for span in capture.span_exporter.get_finished_spans()
        if span.instrumentation_scope is not None
        and span.instrumentation_scope.name == telemetry.INSTRUMENTATION_SCOPE
    ]


def _metric_map(reader: InMemoryMetricReader) -> dict[str, Any]:
    data = reader.get_metrics_data()
    if data is None:
        return {}
    return {
        metric.name: metric
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        if scope_metrics.scope.name == telemetry.INSTRUMENTATION_SCOPE
        for metric in scope_metrics.metrics
    }


def _counter_total(metric: Any) -> int:
    return sum(point.value for point in metric.data.data_points)


async def test_mcp_trace_context_is_parent_and_only_trace_context_reaches_umami(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
) -> None:
    seen_headers: httpx.Headers | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers
        seen_headers = request.headers
        return httpx.Response(200, json={"visitors": 1})

    _patch_async_client(monkeypatch, handler)
    monkeypatch.setenv("UMAMI_API_KEY", "mcp-trace-api-key")
    meta = cast(
        RequestParamsMeta,
        {
            "traceparent": f"00-{TRACE_ID}-{REMOTE_PARENT_ID}-01",
            "tracestate": "vendor=opaque-state",
            "baggage": "private-baggage=must-not-reach-umami",
        },
    )

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "get_active",
            {"website_id": "11111111-1111-4111-8111-111111111111"},
            meta=meta,
        )

    assert result.is_error is False
    assert seen_headers is not None
    assert "baggage" not in seen_headers
    outgoing_traceparent = seen_headers["traceparent"]
    assert outgoing_traceparent.split("-")[1] == TRACE_ID
    assert seen_headers["tracestate"] == "vendor=opaque-state"

    spans = otel_capture.span_exporter.get_finished_spans()
    umami_span = next(
        span
        for span in spans
        if span.instrumentation_scope is not None
        and span.instrumentation_scope.name == telemetry.INSTRUMENTATION_SCOPE
        and span.name == "umami.request GET /websites/{websiteId}/active"
    )
    mcp_span = next(
        span
        for span in spans
        if span.instrumentation_scope is not None
        and span.instrumentation_scope.name == "mcp-python-sdk"
        and span.name == "tools/call get_active"
    )
    assert umami_span.parent is not None
    assert umami_span.parent.span_id == mcp_span.context.span_id
    assert umami_span.context.trace_id == mcp_span.context.trace_id == int(TRACE_ID, 16)
    assert outgoing_traceparent.split("-")[2] == f"{umami_span.context.span_id:016x}"


async def test_success_on_first_send_has_zero_retries_and_records_duration(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
) -> None:
    _patch_async_client(monkeypatch, lambda _: httpx.Response(200, json=WEBSITES))
    client = UmamiClient(_settings())
    try:
        await client.get_websites()
    finally:
        await client.aclose()

    request_span = next(
        span for span in _application_spans(otel_capture) if span.name.startswith("umami.request")
    )
    assert request_span.attributes is not None
    assert request_span.attributes[telemetry.UMAMI_RETRY_COUNT] == 0
    assert request_span.attributes[telemetry.UMAMI_OUTCOME] == "success"
    assert request_span.attributes[telemetry.HTTP_RESPONSE_STATUS_CODE] == 200

    metrics = _metric_map(otel_capture.metric_reader)
    assert telemetry.REQUEST_DURATION in metrics
    assert telemetry.RETRIES not in metrics
    point = metrics[telemetry.REQUEST_DURATION].data.data_points[0]
    assert point.count == 1
    assert point.sum >= 0


async def test_retry_rate_limit_refresh_error_metrics_and_units(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
) -> None:
    login_calls = 0
    analytics_calls = 0

    def successful_after_refresh_and_rate_limit(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, analytics_calls
        if request.url.path.endswith("/auth/login"):
            login_calls += 1
            return httpx.Response(200, json={"token": f"token-{login_calls}"})
        analytics_calls += 1
        if analytics_calls == 1:
            return httpx.Response(401, json={"detail": "expired"})
        if analytics_calls == 2:
            return httpx.Response(429, json={"detail": "slow down"})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, successful_after_refresh_and_rate_limit)
    client = UmamiClient(_settings(login=True), _sleep=lambda _: asyncio.sleep(0))
    try:
        await client.get_websites()
    finally:
        await client.aclose()

    success_span = next(
        span for span in _application_spans(otel_capture) if span.name.startswith("umami.request")
    )
    assert success_span.attributes is not None
    assert success_span.attributes[telemetry.UMAMI_RETRY_COUNT] == 2
    assert success_span.attributes[telemetry.HTTP_RESPONSE_STATUS_CODE] == 200
    assert success_span.attributes[telemetry.UMAMI_OUTCOME] == "success"
    login_spans = [
        span for span in _application_spans(otel_capture) if span.name == "umami.auth.login"
    ]
    assert len(login_spans) == 2
    assert success_span.context is not None
    for login_span in login_spans:
        assert login_span.parent is not None
        assert login_span.parent.span_id == success_span.context.span_id
    assert login_calls == 2
    assert analytics_calls == 3

    def rejected(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "private upstream error"})

    _patch_async_client(monkeypatch, rejected)
    failing_client = UmamiClient(_settings())
    try:
        with pytest.raises(UmamiUpstreamError):
            await failing_client.get_websites()
    finally:
        await failing_client.aclose()

    error_span = [
        span for span in _application_spans(otel_capture) if span.name.startswith("umami.request")
    ][-1]
    assert error_span.status.status_code.name == "ERROR"
    assert error_span.status.description == "upstream"
    assert error_span.attributes is not None
    assert error_span.attributes[telemetry.ERROR_TYPE] == "upstream"

    metrics = _metric_map(otel_capture.metric_reader)
    assert set(metrics) == {
        telemetry.REQUEST_DURATION,
        telemetry.REQUEST_ERRORS,
        telemetry.RETRIES,
        telemetry.RATE_LIMITS,
        telemetry.TOKEN_REFRESHES,
    }
    assert metrics[telemetry.REQUEST_DURATION].unit == "s"
    for name in {
        telemetry.REQUEST_ERRORS,
        telemetry.RETRIES,
        telemetry.RATE_LIMITS,
        telemetry.TOKEN_REFRESHES,
    }:
        assert metrics[name].unit == "1"

    duration_points = metrics[telemetry.REQUEST_DURATION].data.data_points
    assert sum(point.count for point in duration_points) == 2
    assert {point.attributes[telemetry.UMAMI_OUTCOME] for point in duration_points} == {
        "success",
        "error",
    }
    assert _counter_total(metrics[telemetry.REQUEST_ERRORS]) == 1
    assert _counter_total(metrics[telemetry.RETRIES]) == 2
    assert _counter_total(metrics[telemetry.RATE_LIMITS]) == 1
    assert _counter_total(metrics[telemetry.TOKEN_REFRESHES]) == 1
    retry_causes = {
        point.attributes[telemetry.UMAMI_RETRY_CAUSE]
        for point in metrics[telemetry.RETRIES].data.data_points
    }
    assert retry_causes == {"authentication_refresh", "rate_limit"}

    for metric in metrics.values():
        for point in metric.data.data_points:
            assert set(point.attributes).issubset(ALLOWED_ATTRIBUTES)


async def test_exhausted_rate_limits_count_every_response_and_one_logical_error(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
) -> None:
    _patch_async_client(monkeypatch, lambda _: httpx.Response(429, json={"detail": "limited"}))
    client = UmamiClient(_settings(), _sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(UmamiRateLimitError, match="rate-limited"):
            await client.get_websites()
    finally:
        await client.aclose()

    request_span = next(
        span for span in _application_spans(otel_capture) if span.name.startswith("umami.request")
    )
    assert request_span.attributes is not None
    assert request_span.attributes[telemetry.UMAMI_RETRY_COUNT] == 2
    assert request_span.attributes[telemetry.HTTP_RESPONSE_STATUS_CODE] == 429
    assert request_span.attributes[telemetry.ERROR_TYPE] == "rate_limit"

    metrics = _metric_map(otel_capture.metric_reader)
    assert _counter_total(metrics[telemetry.RATE_LIMITS]) == 3
    assert _counter_total(metrics[telemetry.RETRIES]) == 2
    assert _counter_total(metrics[telemetry.REQUEST_ERRORS]) == 1


async def test_concurrent_401_responses_count_one_real_token_refresh(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
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
            return httpx.Response(401, json={"detail": "expired"})
        return httpx.Response(200, json=WEBSITES)

    _patch_async_client(monkeypatch, handler)
    client = UmamiClient(_settings(login=True))
    try:
        await asyncio.gather(client.get_websites(), client.get_websites())
    finally:
        await client.aclose()

    metrics = _metric_map(otel_capture.metric_reader)
    assert login_calls == 2
    assert _counter_total(metrics[telemetry.TOKEN_REFRESHES]) == 1
    assert _counter_total(metrics[telemetry.RETRIES]) == 2


async def test_exported_telemetry_redacts_secrets_payloads_uuid_and_queries(
    monkeypatch: pytest.MonkeyPatch,
    otel_capture: OtelCapture,
) -> None:
    bearer_token = "synthetic-bearer-token"
    website_id = UUID("deaddead-dead-4ead-8ead-deaddeaddead")
    search_value = "synthetic-private-search"
    filter_value = "synthetic-private-filter"
    upstream_body = "synthetic-private-upstream-body"

    def login_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": bearer_token})
        return httpx.Response(500, json={"detail": upstream_body, "password": "echoed"})

    _patch_async_client(monkeypatch, login_handler)
    login_client = UmamiClient(_settings(login=True), _sleep=lambda _: asyncio.sleep(0))
    try:
        with pytest.raises(UmamiUpstreamError):
            await login_client.get_stats(
                website_id,
                params={"search": search_value, "filter": filter_value},
            )
    finally:
        await login_client.aclose()

    _patch_async_client(
        monkeypatch,
        lambda _: httpx.Response(400, json={"detail": upstream_body}),
    )
    api_key_client = UmamiClient(_settings())
    try:
        with pytest.raises(UmamiUpstreamError):
            await api_key_client.get_websites(search=search_value)
    finally:
        await api_key_client.aclose()

    mcp_api_key = "mcp-redaction-api-key"
    _patch_async_client(
        monkeypatch,
        lambda _: httpx.Response(400, json={"detail": upstream_body}),
    )
    monkeypatch.setenv("UMAMI_API_KEY", mcp_api_key)
    async with Client(server) as mcp_client:
        result = await mcp_client.call_tool(
            "get_active",
            {"website_id": str(website_id)},
        )
    assert result.is_error is True

    spans = list(otel_capture.span_exporter.get_finished_spans())
    serialized_spans = [
        {
            "name": span.name,
            "attributes": dict(span.attributes or {}),
            "events": [
                {"name": event.name, "attributes": dict(event.attributes or {})}
                for event in span.events
            ],
            "status": {
                "code": span.status.status_code.name,
                "description": span.status.description,
            },
        }
        for span in spans
    ]
    metrics = _metric_map(otel_capture.metric_reader)
    serialized_metrics = [
        {
            "name": metric.name,
            "unit": metric.unit,
            "points": [
                {
                    "attributes": dict(point.attributes),
                    "value": getattr(point, "value", None),
                    "sum": getattr(point, "sum", None),
                    "count": getattr(point, "count", None),
                }
                for point in metric.data.data_points
            ],
        }
        for metric in metrics.values()
    ]
    exported = json.dumps(
        {"spans": serialized_spans, "metrics": serialized_metrics},
        default=str,
        sort_keys=True,
    )

    secrets = {
        "synthetic-api-key",
        mcp_api_key,
        "synthetic-user",
        "synthetic-password",
        bearer_token,
        str(website_id),
        search_value,
        filter_value,
        upstream_body,
    }
    for secret in secrets:
        assert secret not in exported
    assert all(not span.events for span in spans)
    for span in spans:
        if (
            span.instrumentation_scope is not None
            and span.instrumentation_scope.name == telemetry.INSTRUMENTATION_SCOPE
        ):
            assert set(span.attributes or {}).issubset(ALLOWED_ATTRIBUTES)


def test_otel_sdk_disabled_is_noop_in_a_fresh_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    code = """
import asyncio
import httpx
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

span_exporter = InMemorySpanExporter()
tracer_provider = TracerProvider(shutdown_on_exit=False)
tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(tracer_provider)
metric_reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader], shutdown_on_exit=False))

from umami_mcp_server.settings import Settings
from umami_mcp_server.umami_client import UmamiClient

original_async_client = httpx.AsyncClient
transport = httpx.MockTransport(
    lambda _: httpx.Response(200, json={"data": [], "count": 0, "page": 1, "pageSize": 10})
)
def client_factory(*args, **kwargs):
    return original_async_client(*args, **kwargs, transport=transport)
httpx.AsyncClient = client_factory

async def request():
    client = UmamiClient(Settings(umami_api_key="disabled-test-key"))
    try:
        await client.get_websites()
    finally:
        await client.aclose()

asyncio.run(request())
assert span_exporter.get_finished_spans() == ()
assert metric_reader.get_metrics_data() is None
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        env=os.environ.copy(),
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
