from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Any, Literal, TypeVar
from uuid import UUID

import httpx
from pydantic import TypeAdapter, ValidationError

from .models import (
    ActiveVisitors,
    ExpandedMetric,
    Metric,
    Pageviews,
    WebsitePage,
    WebsiteStats,
)
from . import telemetry
from .settings import Settings

logger = logging.getLogger(__name__)
# HTTPX/httpcore log complete URLs and headers at INFO/DEBUG. The server emits its own
# sanitized request diagnostics instead.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

MAX_ATTEMPTS = 3
BASE_RETRY_DELAY_S = 0.5
MAX_RETRY_DELAY_S = 60.0


class UmamiError(RuntimeError):
    """Base class for safe errors exposed by the Umami client."""


class UmamiAuthenticationError(UmamiError):
    pass


class UmamiRateLimitError(UmamiError):
    pass


class UmamiTimeoutError(UmamiError):
    pass


class UmamiNetworkError(UmamiError):
    pass


class UmamiUpstreamError(UmamiError):
    pass


class UmamiInvalidResponseError(UmamiError):
    pass


T = TypeVar("T")
Sleep = Callable[[float], Awaitable[object]]
RandomUniform = Callable[[float, float], float]
Clock = Callable[[], datetime]

_WEBSITE_PAGE_ADAPTER = TypeAdapter(WebsitePage)
_WEBSITE_STATS_ADAPTER = TypeAdapter(WebsiteStats)
_PAGEVIEWS_ADAPTER = TypeAdapter(Pageviews)
_METRICS_ADAPTER = TypeAdapter(list[Metric | ExpandedMetric])
_ACTIVE_VISITORS_ADAPTER = TypeAdapter(ActiveVisitors)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UmamiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        timeout_s: float = 30.0,
        _sleep: Sleep | None = None,
        _random_uniform: RandomUniform | None = None,
        _clock: Clock | None = None,
    ) -> None:
        base_url = settings.umami_api_base.rstrip("/")
        self._auth_mode: Literal["api_key", "login"] = (
            "api_key" if settings.umami_api_key else "login"
        )
        self._username = settings.umami_username
        self._password = settings.umami_password
        self._token: str | None = None
        self._token_lock = asyncio.Lock()
        self._sleep = _sleep or asyncio.sleep
        self._random_uniform = _random_uniform or random.uniform
        self._clock = _clock or _utc_now

        headers: dict[str, str] = {"Accept": "application/json"}
        if self._auth_mode == "api_key":
            api_key = settings.umami_api_key
            if not api_key:
                raise UmamiAuthenticationError("An Umami API key is required.")
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _login(self) -> str:
        endpoint = "/auth/login"
        outcome: telemetry.Outcome = "error"

        with telemetry.login_span(self._auth_mode) as span:
            try:
                if not self._username or not self._password:
                    raise UmamiAuthenticationError("Umami login credentials are required.")

                headers: dict[str, str] = {}
                telemetry.inject_trace_context(headers)
                try:
                    response = await self._client.post(
                        endpoint,
                        json={"username": self._username, "password": self._password},
                        headers=headers,
                    )
                except httpx.TimeoutException:
                    self._log_failure(endpoint, None, 1, UmamiTimeoutError)
                    raise UmamiTimeoutError("The Umami login request timed out.") from None
                except httpx.TransportError:
                    self._log_failure(endpoint, None, 1, UmamiNetworkError)
                    raise UmamiNetworkError(
                        "The Umami login request could not be completed."
                    ) from None

                try:
                    telemetry.set_response_status(span, response.status_code)
                    if response.status_code in {401, 403}:
                        self._log_failure(
                            endpoint, response.status_code, 1, UmamiAuthenticationError
                        )
                        raise UmamiAuthenticationError("Authentication with Umami failed.")
                    if response.status_code == 429:
                        telemetry.record_rate_limit(method="POST", endpoint=endpoint)
                        self._log_failure(endpoint, response.status_code, 1, UmamiRateLimitError)
                        raise UmamiRateLimitError("Umami rate-limited the login request.")
                    if not 200 <= response.status_code < 300:
                        self._log_failure(endpoint, response.status_code, 1, UmamiUpstreamError)
                        raise UmamiUpstreamError("Umami rejected the login request.")

                    try:
                        payload = response.json()
                    except ValueError:
                        self._log_failure(
                            endpoint, response.status_code, 1, UmamiInvalidResponseError
                        )
                        raise UmamiInvalidResponseError(
                            "Umami returned an invalid login response."
                        ) from None

                    token = payload.get("token") if isinstance(payload, dict) else None
                    if not isinstance(token, str) or not token:
                        self._log_failure(
                            endpoint, response.status_code, 1, UmamiInvalidResponseError
                        )
                        raise UmamiInvalidResponseError("Umami returned an invalid login response.")
                    outcome = "success"
                    return token
                finally:
                    await response.aclose()
            except asyncio.CancelledError as error:
                telemetry.set_error(span, error)
                raise
            except Exception as error:
                telemetry.set_error(span, error)
                raise
            finally:
                telemetry.set_outcome(span, outcome)

    async def _ensure_token(self) -> str | None:
        if self._auth_mode != "login":
            return None
        if self._token is not None:
            return self._token

        async with self._token_lock:
            if self._token is None:
                self._token = await self._login()
            return self._token

    async def _refresh_token(
        self,
        failed_token: str | None,
        *,
        method: str,
        endpoint: str,
    ) -> str:
        async with self._token_lock:
            if self._token is not None and self._token != failed_token:
                return self._token
            if self._token == failed_token:
                self._token = None
            telemetry.record_token_refresh(method=method, endpoint=endpoint)
            self._token = await self._login()
            return self._token

    @staticmethod
    def _log_failure(
        endpoint: str,
        status_code: int | None,
        attempt: int,
        error_class: type[UmamiError],
    ) -> None:
        logger.warning(
            "Umami request failed endpoint=%s status=%s attempt=%d error=%s",
            telemetry.normalize_endpoint(endpoint),
            status_code,
            attempt,
            error_class.__name__,
        )

    @staticmethod
    def _log_validation_failure(
        endpoint: str,
        status_code: int,
        attempt: int,
        error: ValidationError,
    ) -> None:
        details = [
            {"location": item["loc"], "type": item["type"]}
            for item in error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        ]
        logger.warning(
            "Umami request failed endpoint=%s status=%s attempt=%d error=%s validation=%s",
            telemetry.normalize_endpoint(endpoint),
            status_code,
            attempt,
            UmamiInvalidResponseError.__name__,
            details,
        )

    def _backoff_delay(self, retry_index: int) -> float:
        upper_bound = min(BASE_RETRY_DELAY_S * (2**retry_index), MAX_RETRY_DELAY_S)
        return min(max(self._random_uniform(0.0, upper_bound), 0.0), MAX_RETRY_DELAY_S)

    def _retry_after_delay(self, value: str | None, retry_index: int) -> float:
        if value is not None:
            try:
                seconds = float(value)
                if seconds >= 0:
                    return min(seconds, MAX_RETRY_DELAY_S)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    now = self._clock()
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)
                    seconds = max(0.0, (retry_at - now.astimezone(timezone.utc)).total_seconds())
                    return min(seconds, MAX_RETRY_DELAY_S)
                except (TypeError, ValueError, OverflowError):
                    pass
        return self._backoff_delay(retry_index)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        adapter: TypeAdapter[T],
        params: dict[str, Any] | None = None,
    ) -> T:
        retryable_method = method.upper() == "GET"
        refreshed = False
        retry_count = 0
        outcome: telemetry.Outcome = "error"
        started_at = perf_counter()

        with telemetry.request_span(method, path, self._auth_mode) as span:
            try:
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    token_used = await self._ensure_token()
                    headers: dict[str, str] = {}
                    if self._auth_mode == "login" and token_used is not None:
                        headers["Authorization"] = f"Bearer {token_used}"
                    telemetry.inject_trace_context(headers)

                    try:
                        response = await self._client.request(
                            method,
                            path,
                            params=params,
                            headers=headers,
                        )
                    except httpx.TimeoutException:
                        self._log_failure(path, None, attempt, UmamiTimeoutError)
                        if retryable_method and attempt < MAX_ATTEMPTS:
                            telemetry.record_retry(
                                method=method,
                                endpoint=path,
                                cause="timeout",
                            )
                            retry_count += 1
                            await self._sleep(self._backoff_delay(attempt - 1))
                            continue
                        raise UmamiTimeoutError(
                            "The Umami request timed out after three attempts."
                        ) from None
                    except httpx.TransportError:
                        self._log_failure(path, None, attempt, UmamiNetworkError)
                        if retryable_method and attempt < MAX_ATTEMPTS:
                            telemetry.record_retry(
                                method=method,
                                endpoint=path,
                                cause="network",
                            )
                            retry_count += 1
                            await self._sleep(self._backoff_delay(attempt - 1))
                            continue
                        raise UmamiNetworkError(
                            "The Umami request could not be completed after three attempts."
                        ) from None

                    try:
                        status_code = response.status_code
                        telemetry.set_response_status(span, status_code)
                        if status_code == 401:
                            self._log_failure(path, status_code, attempt, UmamiAuthenticationError)
                            if self._auth_mode == "api_key" or refreshed or attempt == MAX_ATTEMPTS:
                                raise UmamiAuthenticationError("Authentication with Umami failed.")
                            await self._refresh_token(
                                token_used,
                                method=method,
                                endpoint=path,
                            )
                            refreshed = True
                            telemetry.record_retry(
                                method=method,
                                endpoint=path,
                                cause="authentication_refresh",
                            )
                            retry_count += 1
                            continue

                        if status_code == 403:
                            self._log_failure(path, status_code, attempt, UmamiAuthenticationError)
                            raise UmamiAuthenticationError("The Umami request is not authorized.")

                        if status_code in _RETRYABLE_STATUS_CODES:
                            is_rate_limit = status_code == 429
                            error_class = (
                                UmamiRateLimitError if is_rate_limit else UmamiUpstreamError
                            )
                            if is_rate_limit:
                                telemetry.record_rate_limit(method=method, endpoint=path)
                            self._log_failure(path, status_code, attempt, error_class)
                            if retryable_method and attempt < MAX_ATTEMPTS:
                                cause: telemetry.RetryCause = (
                                    "rate_limit" if is_rate_limit else "server_error"
                                )
                                telemetry.record_retry(
                                    method=method,
                                    endpoint=path,
                                    cause=cause,
                                )
                                retry_count += 1
                                delay = (
                                    self._retry_after_delay(
                                        response.headers.get("Retry-After"), attempt - 1
                                    )
                                    if is_rate_limit
                                    else self._backoff_delay(attempt - 1)
                                )
                                await self._sleep(delay)
                                continue
                            if is_rate_limit:
                                raise UmamiRateLimitError("Umami rate-limited the request.")
                            raise UmamiUpstreamError("Umami is temporarily unavailable.")

                        if not 200 <= status_code < 300:
                            self._log_failure(path, status_code, attempt, UmamiUpstreamError)
                            raise UmamiUpstreamError(
                                f"Umami rejected the request with status {status_code}."
                            )

                        try:
                            payload = response.json()
                        except ValueError:
                            self._log_failure(path, status_code, attempt, UmamiInvalidResponseError)
                            raise UmamiInvalidResponseError(
                                "Umami returned an invalid response."
                            ) from None

                        try:
                            result = adapter.validate_python(payload)
                        except ValidationError as error:
                            self._log_validation_failure(path, status_code, attempt, error)
                            raise UmamiInvalidResponseError(
                                "Umami returned an invalid response."
                            ) from None

                        outcome = "success"
                        return result
                    finally:
                        await response.aclose()

                raise AssertionError("unreachable")
            except asyncio.CancelledError as error:
                category = telemetry.set_error(span, error)
                telemetry.record_request_error(
                    method=method,
                    endpoint=path,
                    category=category,
                )
                raise
            except Exception as error:
                category = telemetry.set_error(span, error)
                telemetry.record_request_error(
                    method=method,
                    endpoint=path,
                    category=category,
                )
                raise
            finally:
                telemetry.set_retry_count(span, retry_count)
                telemetry.set_outcome(span, outcome)
                telemetry.record_request_duration(
                    perf_counter() - started_at,
                    method=method,
                    endpoint=path,
                    outcome=outcome,
                )

    async def get_websites(
        self,
        *,
        include_teams: bool = False,
        search: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> WebsitePage:
        params: dict[str, Any] = {
            "includeTeams": "true" if include_teams else "false",
            "page": page,
            "pageSize": page_size,
        }
        if search:
            params["search"] = search
        return await self._request("GET", "/websites", adapter=_WEBSITE_PAGE_ADAPTER, params=params)

    async def get_stats(self, website_id: UUID, *, params: dict[str, Any]) -> WebsiteStats:
        return await self._request(
            "GET",
            f"/websites/{website_id}/stats",
            adapter=_WEBSITE_STATS_ADAPTER,
            params=params,
        )

    async def get_pageviews(self, website_id: UUID, *, params: dict[str, Any]) -> Pageviews:
        return await self._request(
            "GET",
            f"/websites/{website_id}/pageviews",
            adapter=_PAGEVIEWS_ADAPTER,
            params=params,
        )

    async def get_metrics(
        self,
        website_id: UUID,
        *,
        expanded: bool,
        params: dict[str, Any],
    ) -> list[Metric | ExpandedMetric]:
        endpoint = (
            f"/websites/{website_id}/metrics/expanded"
            if expanded
            else f"/websites/{website_id}/metrics"
        )
        return await self._request("GET", endpoint, adapter=_METRICS_ADAPTER, params=params)

    async def get_active(self, website_id: UUID) -> ActiveVisitors:
        return await self._request(
            "GET", f"/websites/{website_id}/active", adapter=_ACTIVE_VISITORS_ADAPTER
        )
