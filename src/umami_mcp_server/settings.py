from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    umami_api_key: str | None = Field(
        default=None,
        validation_alias="UMAMI_API_KEY",
        description=(
            "Umami Cloud API key. Required for Umami Cloud deployments (https://api.umami.is)."
        ),
    )
    umami_username: str | None = Field(
        default=None,
        validation_alias="UMAMI_USERNAME",
        description="Umami username (self-hosted only).",
    )
    umami_password: str | None = Field(
        default=None,
        validation_alias="UMAMI_PASSWORD",
        description="Umami password (self-hosted only).",
    )
    umami_api_base: str = Field(
        default="https://api.umami.is/v1",
        validation_alias="UMAMI_API_BASE",
        description="Base URL for Umami API (Umami Cloud: https://api.umami.is/v1)",
    )

    @model_validator(mode="after")
    def _validate_auth(self) -> "Settings":
        has_api_key = bool(self.umami_api_key)
        has_username = bool(self.umami_username)
        has_password = bool(self.umami_password)

        if has_api_key:
            return self

        if has_username != has_password:
            raise ValueError(
                "Invalid Umami auth configuration. Provide either UMAMI_API_KEY (Umami Cloud) "
                "or both UMAMI_USERNAME and UMAMI_PASSWORD (self-hosted)."
            )

        if not (has_username and has_password):
            raise ValueError(
                "Missing Umami credentials. Provide UMAMI_API_KEY (Umami Cloud) or both "
                "UMAMI_USERNAME and UMAMI_PASSWORD (self-hosted). Note: Umami Cloud only "
                "supports API keys."
            )

        parsed = urlparse(self.umami_api_base)
        host = (parsed.hostname or "").lower()
        looks_like_cloud = host == "api.umami.is"
        if looks_like_cloud:
            raise ValueError(
                "UMAMI_USERNAME/UMAMI_PASSWORD are only supported for self-hosted Umami. "
                "Umami Cloud requires UMAMI_API_KEY. For self-hosted, set UMAMI_API_BASE to "
                "your instance API root (e.g. https://your-umami.example/api)."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
