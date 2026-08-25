from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Literal

from opentelemetry import metrics, trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

INSTRUMENTATION_SCOPE = "umami-mcp-server"

REQUEST_DURATION = "umami.client.request.duration"
REQUEST_ERRORS = "umami.client.request.errors"
RETRIES = "umami.client.retries"
RATE_LIMITS = "umami.client.rate_limits"
TOKEN_REFRESHES = "umami.client.token.refreshes"

HTTP_REQUEST_METHOD = "http.request.method"
HTTP_RESPONSE_STATUS_CODE = "http.response.status_code"
UMAMI_ENDPOINT = "umami.endpoint"
UMAMI_AUTH_MODE = "umami.auth.mode"
UMAMI_RETRY_COUNT = "umami.retry.count"
UMAMI_OUTCOME = "umami.outcome"
UMAMI_RETRY_CAUSE = "umami.retry.cause"
ERROR_TYPE = "error.type"

Outcome = Literal["success", "error"]
RetryCause = Literal[
    "authentication_refresh",
    "timeout",
    "network",
    "rate_limit",
    "server_error",
]

_TRACER = trace.get_tracer(INSTRUMENTATION_SCOPE)
_METER = metrics.get_meter(INSTRUMENTATION_SCOPE)
_TRACE_CONTEXT_PROPAGATOR = TraceContextTextMapPropagator()

_REQUEST_DURATION = _METER.create_histogram(
    REQUEST_DURATION,
    unit="s",
    description="Duration of a logical Umami analytics request, including login and retries.",
)
_REQUEST_ERRORS = _METER.create_counter(
    REQUEST_ERRORS,
    unit="1",
    description="Logical Umami analytics requests that ended with an error.",
)
_RETRIES = _METER.create_counter(
    RETRIES,
    unit="1",
    description="Additional Umami analytics request sends.",
)
_RATE_LIMITS = _METER.create_counter(
    RATE_LIMITS,
    unit="1",
    description="Umami HTTP 429 responses.",
)
_TOKEN_REFRESHES = _METER.create_counter(
    TOKEN_REFRESHES,
    unit="1",
    description="Token refreshes that performed a new Umami login.",
)

_UUID_PATH_RE = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)
_ALLOWED_ENDPOINTS = frozenset(
    {
        "/websites",
        "/websites/{websiteId}/stats",
        "/websites/{websiteId}/pageviews",
        "/websites/{websiteId}/metrics",
        "/websites/{websiteId}/metrics/expanded",
        "/websites/{websiteId}/active",
        "/auth/login",
    }
)
_ERROR_CATEGORIES = {
    "UmamiAuthenticationError": "authentication",
    "UmamiRateLimitError": "rate_limit",
    "UmamiTimeoutError": "timeout",
    "UmamiNetworkError": "network",
    "UmamiUpstreamError": "upstream",
    "UmamiInvalidResponseError": "invalid_response",
    "CancelledError": "cancelled",
}


def normalize_endpoint(path: str) -> str:
    """Return a bounded-cardinality endpoint without accepting arbitrary URLs."""

    endpoint = _UUID_PATH_RE.sub("/{websiteId}", path)
    return endpoint if endpoint in _ALLOWED_ENDPOINTS else "/unknown"


def error_category(error: BaseException) -> str:
    """Map an application exception to a controlled, payload-free category."""

    return _ERROR_CATEGORIES.get(type(error).__name__, "unknown")


def _method(value: str) -> str:
    method = value.upper()
    return method if method in {"GET", "POST"} else "OTHER"


def _auth_mode(value: str) -> str:
    return value if value in {"api_key", "login"} else "unknown"


@contextmanager
def request_span(method: str, endpoint: str, auth_mode: str) -> Iterator[Span]:
    safe_method = _method(method)
    safe_endpoint = normalize_endpoint(endpoint)
    with _TRACER.start_as_current_span(
        f"umami.request {safe_method} {safe_endpoint}",
        kind=SpanKind.CLIENT,
        attributes={
            HTTP_REQUEST_METHOD: safe_method,
            UMAMI_ENDPOINT: safe_endpoint,
            UMAMI_AUTH_MODE: _auth_mode(auth_mode),
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


@contextmanager
def login_span(auth_mode: str) -> Iterator[Span]:
    with _TRACER.start_as_current_span(
        "umami.auth.login",
        kind=SpanKind.CLIENT,
        attributes={
            HTTP_REQUEST_METHOD: "POST",
            UMAMI_ENDPOINT: "/auth/login",
            UMAMI_AUTH_MODE: _auth_mode(auth_mode),
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        yield span


def inject_trace_context(headers: MutableMapping[str, str]) -> None:
    """Inject only W3C traceparent and tracestate into a dedicated HTTP carrier."""

    _TRACE_CONTEXT_PROPAGATOR.inject(headers)  # type: ignore[arg-type]


def set_error(span: Span, error: BaseException) -> str:
    category = error_category(error)
    span.set_attribute(ERROR_TYPE, category)
    span.set_status(Status(StatusCode.ERROR, category))
    return category


def record_request_duration(
    duration_s: float,
    *,
    method: str,
    endpoint: str,
    outcome: Outcome,
) -> None:
    _REQUEST_DURATION.record(
        max(duration_s, 0.0),
        {
            HTTP_REQUEST_METHOD: _method(method),
            UMAMI_ENDPOINT: normalize_endpoint(endpoint),
            UMAMI_OUTCOME: outcome,
        },
    )


def record_request_error(*, method: str, endpoint: str, category: str) -> None:
    safe_category = category if category in {*_ERROR_CATEGORIES.values(), "unknown"} else "unknown"
    _REQUEST_ERRORS.add(
        1,
        {
            HTTP_REQUEST_METHOD: _method(method),
            UMAMI_ENDPOINT: normalize_endpoint(endpoint),
            UMAMI_OUTCOME: "error",
            ERROR_TYPE: safe_category,
        },
    )


def record_retry(*, method: str, endpoint: str, cause: RetryCause) -> None:
    _RETRIES.add(
        1,
        {
            HTTP_REQUEST_METHOD: _method(method),
            UMAMI_ENDPOINT: normalize_endpoint(endpoint),
            UMAMI_RETRY_CAUSE: cause,
        },
    )


def record_rate_limit(*, method: str, endpoint: str) -> None:
    _RATE_LIMITS.add(
        1,
        {
            HTTP_REQUEST_METHOD: _method(method),
            UMAMI_ENDPOINT: normalize_endpoint(endpoint),
        },
    )


def record_token_refresh(*, method: str, endpoint: str) -> None:
    _TOKEN_REFRESHES.add(
        1,
        {
            HTTP_REQUEST_METHOD: _method(method),
            UMAMI_ENDPOINT: normalize_endpoint(endpoint),
        },
    )
