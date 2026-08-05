from __future__ import annotations

import os
import subprocess
import sys

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


def test_settings_rejects_multiple_auth_modes() -> None:
    with pytest.raises(ValueError, match=r"not both") as caught:
        Settings(
            umami_api_key="secret-api-key",
            umami_username="secret-user",
            umami_password="secret-password",
            umami_api_base="https://example.com/api",
        )

    message = str(caught.value)
    assert "secret-api-key" not in message
    assert "secret-user" not in message
    assert "secret-password" not in message


def test_startup_configuration_traceback_hides_credentials() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "UMAMI_API_KEY": "subprocess-secret-key",
            "UMAMI_USERNAME": "subprocess-secret-user",
            "UMAMI_PASSWORD": "subprocess-secret-password",
            "UMAMI_API_BASE": "https://example.com/api",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "umami_mcp_server"],
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode != 0
    output = completed.stdout + completed.stderr
    assert "subprocess-secret-key" not in output
    assert "subprocess-secret-user" not in output
    assert "subprocess-secret-password" not in output
