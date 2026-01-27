from __future__ import annotations

import pytest

from umami_mcp_server.settings import Settings


def test_settings_cloud_api_key_ok() -> None:
    settings = Settings(
        umami_api_key="k",
        umami_api_base="https://api.umami.is/v1",
    )
    assert settings.umami_api_key == "k"


def test_settings_self_hosted_username_password_ok() -> None:
    settings = Settings(
        umami_username="u",
        umami_password="p",
        umami_api_base="https://example.com/api",
    )
    assert settings.umami_username == "u"
    assert settings.umami_password == "p"


def test_settings_missing_credentials_raises() -> None:
    with pytest.raises(ValueError, match=r"Missing Umami credentials"):
        Settings(umami_api_base="https://example.com/api")


def test_settings_partial_username_password_raises() -> None:
    with pytest.raises(ValueError, match=r"Invalid Umami auth configuration"):
        Settings(
            umami_username="u",
            umami_api_base="https://example.com/api",
        )


def test_settings_cloud_rejects_username_password() -> None:
    with pytest.raises(ValueError, match=r"Umami Cloud requires UMAMI_API_KEY"):
        Settings(
            umami_username="u",
            umami_password="p",
            umami_api_base="https://api.umami.is/v1",
        )
