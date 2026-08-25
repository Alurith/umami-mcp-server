from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    umami_api_key: str | None = Field(
        default=None,
        validation_alias="UMAMI_API_KEY",
        description="API key for Umami Cloud.",
    )
    umami_username: str | None = Field(
        default=None,
        validation_alias="UMAMI_USERNAME",
        description="Umami username (self-hosted v3.x only).",
    )
    umami_password: str | None = Field(
        default=None,
        validation_alias="UMAMI_PASSWORD",
        description="Umami password (self-hosted v3.x only).",
    )
    umami_api_base: str = Field(
        default="https://api.umami.is/v1",
        validation_alias="UMAMI_API_BASE",
        description=(
            "API root (Cloud: https://api.umami.is/v1; self-hosted v3.x: https://host.example/api)."
        ),
    )

    @model_validator(mode="after")
    def _validate_auth(self) -> "Settings":
        has_api_key = bool(self.umami_api_key)
        has_username = bool(self.umami_username)
        has_password = bool(self.umami_password)

        if has_api_key:
            if has_username or has_password:
                raise ValueError(
                    "Invalid Umami auth configuration. Provide either UMAMI_API_KEY or "
                    "UMAMI_USERNAME and UMAMI_PASSWORD, not both."
                )
            parsed = urlparse(self.umami_api_base)
            if (parsed.hostname or "").lower() != "api.umami.is":
                raise ValueError(
                    "UMAMI_API_KEY is only supported for Umami Cloud. Standard self-hosted "
                    "Umami 3.x requires UMAMI_USERNAME and UMAMI_PASSWORD."
                )
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
                "UMAMI_USERNAME/UMAMI_PASSWORD are only supported for self-hosted Umami v3.x. "
                "Umami Cloud requires UMAMI_API_KEY. For self-hosted v3.x, set UMAMI_API_BASE "
                "to your instance API root (e.g. https://your-umami.example/api)."
            )

        return self
