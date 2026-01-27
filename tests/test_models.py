from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from umami_mcp_server.models import datetime_to_ms, ms_timerange


def test_datetime_to_ms_treats_naive_as_utc() -> None:
    naive = datetime(2026, 1, 1, 0, 0, 0)
    expected = int(naive.replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert datetime_to_ms(naive) == expected


def test_ms_timerange_defaults_to_last_7_days_from_end() -> None:
    end_at = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    start_ms, end_ms = ms_timerange(None, end_at)
    assert end_ms == int(end_at.timestamp() * 1000)

    expected_start = end_at - timedelta(days=7)
    assert start_ms == int(expected_start.timestamp() * 1000)


def test_ms_timerange_raises_when_end_before_start() -> None:
    start_at = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    end_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match=r"end_at must be after start_at"):
        ms_timerange(start_at, end_at)


def test_ms_timerange_treats_naive_inputs_as_utc() -> None:
    start_at = datetime(2026, 1, 1, 0, 0, 0)
    end_at = datetime(2026, 1, 2, 0, 0, 0)
    start_ms, end_ms = ms_timerange(start_at, end_at)

    assert start_ms == int(start_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert end_ms == int(end_at.replace(tzinfo=timezone.utc).timestamp() * 1000)
