from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from .settings import Settings


class UmamiError(RuntimeError):
    pass


class UmamiClient:
    def __init__(self, settings: Settings, *, timeout_s: float = 30.0) -> None:
        base_url = settings.umami_api_base.rstrip("/")
        self._auth_mode: Literal["api_key", "login"] = (
            "api_key" if settings.umami_api_key else "login"
        )
        self._username = settings.umami_username
        self._password = settings.umami_password
        self._token: str | None = None

        headers: dict[str, str] = {"Accept": "application/json"}
        if self._auth_mode == "api_key":
            api_key = settings.umami_api_key
            if not api_key:
                raise UmamiError(
                    "Missing UMAMI_API_KEY. Umami Cloud deployments require an API key."
                )
            headers["x-umami-api-key"] = api_key

        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout_s,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ensure_token(self) -> None:
        if self._auth_mode != "login":
            return
        if self._token is not None:
            return
        if not self._username or not self._password:
            raise UmamiError(
                "Missing UMAMI_USERNAME/UMAMI_PASSWORD. These credentials are only supported "
                "for self-hosted Umami."
            )

        try:
            resp = await self._client.post(
                "/auth/login",
                json={"username": self._username, "password": self._password},
            )
        except httpx.HTTPError as e:
            raise UmamiError(f"Login request failed: {e}") from e

        try:
            if resp.status_code in {401, 403}:
                raise UmamiError(
                    "Authentication failed (check UMAMI_USERNAME/UMAMI_PASSWORD). Note: Umami "
                    "Cloud only supports UMAMI_API_KEY."
                )

            if resp.status_code < 200 or resp.status_code >= 300:
                raise UmamiError(f"Login failed ({resp.status_code}): {resp.text}")

            data = resp.json()
            token = data.get("token")
            if not isinstance(token, str) or not token:
                raise UmamiError("Login succeeded but no token was returned by Umami")

            self._token = token
        finally:
            await resp.aclose()

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None
    ) -> Any:
        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            if self._auth_mode == "login":
                await self._ensure_token()

            try:
                headers: dict[str, str] | None = None
                if self._auth_mode == "login":
                    headers = {"Authorization": f"Bearer {self._token}"}

                resp = await self._client.request(
                    method,
                    path,
                    params=params,
                    headers=headers,
                )
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep(0.25 * (2**attempt))
                continue

            try:
                if resp.status_code in {401, 403}:
                    if self._auth_mode == "api_key":
                        raise UmamiError("Authentication failed (check UMAMI_API_KEY)")
                    raise UmamiError(
                        "Authentication failed (check UMAMI_USERNAME/UMAMI_PASSWORD). Note: "
                        "Umami Cloud only supports UMAMI_API_KEY."
                    )

                if resp.status_code == 429:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue

                if resp.status_code < 200 or resp.status_code >= 300:
                    text = resp.text
                    raise UmamiError(f"Umami API error {resp.status_code}: {text}")

                if resp.status_code == 204:
                    return None

                return resp.json()
            finally:
                await resp.aclose()

        if last_exc is not None:
            raise UmamiError(f"Request failed after retries: {last_exc}")
        raise UmamiError("Request rate-limited (429) after retries")

    async def get_websites(
        self,
        *,
        include_teams: bool = False,
        search: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Any:
        params: dict[str, Any] = {
            "includeTeams": "true" if include_teams else "false",
            "page": page,
            "pageSize": page_size,
        }
        if search:
            params["search"] = search
        return await self._request("GET", "/websites", params=params)

    async def get_stats(self, website_id: str, *, params: dict[str, Any]) -> Any:
        return await self._request("GET", f"/websites/{website_id}/stats", params=params)

    async def get_pageviews(self, website_id: str, *, params: dict[str, Any]) -> Any:
        return await self._request("GET", f"/websites/{website_id}/pageviews", params=params)

    async def get_metrics(self, website_id: str, *, expanded: bool, params: dict[str, Any]) -> Any:
        endpoint = (
            f"/websites/{website_id}/metrics/expanded"
            if expanded
            else f"/websites/{website_id}/metrics"
        )
        return await self._request("GET", endpoint, params=params)

    async def get_active(self, website_id: str) -> Any:
        return await self._request("GET", f"/websites/{website_id}/active")
