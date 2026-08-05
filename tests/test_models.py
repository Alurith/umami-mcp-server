from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from umami_mcp_server.models import (
    ActiveVisitors,
    ExpandedMetric,
    Filters,
    IanaTimezone,
    Metric,
    MetricLimit,
    MetricOffset,
    MetricType,
    Page,
    PageSize,
    Pageviews,
    WebsitePage,
    WebsiteStats,
    datetime_to_ms,
    ms_timerange,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_MODELS: dict[str, TypeAdapter[Any]] = {
    "websites.json": TypeAdapter(WebsitePage),
    "stats.json": TypeAdapter(WebsiteStats),
    "pageviews.json": TypeAdapter(Pageviews),
    "pageviews_compare.json": TypeAdapter(Pageviews),
    "metrics.json": TypeAdapter(list[Metric | ExpandedMetric]),
    "metrics_expanded.json": TypeAdapter(list[Metric | ExpandedMetric]),
    "active.json": TypeAdapter(ActiveVisitors),
}


def test_datetime_to_ms_treats_naive_as_utc() -> None:
    naive = datetime(2026, 1, 1)
    expected = int(naive.replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert datetime_to_ms(naive) == expected


def test_ms_timerange_supports_all_four_input_combinations() -> None:
    now = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    end = datetime(2026, 1, 8, 12, tzinfo=timezone.utc)

    def clock() -> datetime:
        return now

    assert ms_timerange(None, None, _clock=clock) == (
        datetime_to_ms(now - timedelta(days=7)),
        datetime_to_ms(now),
    )
    assert ms_timerange(None, end, _clock=clock) == (
        datetime_to_ms(end - timedelta(days=7)),
        datetime_to_ms(end),
    )
    assert ms_timerange(start, None, _clock=clock) == (
        datetime_to_ms(start),
        datetime_to_ms(now),
    )
    assert ms_timerange(start, end, _clock=clock) == (
        datetime_to_ms(start),
        datetime_to_ms(end),
    )


def test_ms_timerange_treats_naive_inputs_and_clock_as_utc() -> None:
    start = datetime(2026, 1, 1)
    now = datetime(2026, 1, 2)
    assert ms_timerange(start, None, _clock=lambda: now) == (
        datetime_to_ms(start.replace(tzinfo=timezone.utc)),
        datetime_to_ms(now.replace(tzinfo=timezone.utc)),
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        (datetime(2026, 1, 2, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_ms_timerange_rejects_empty_or_inverted_range(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError, match="end_at must be after start_at"):
        ms_timerange(start, end)


def test_iana_timezone_validation() -> None:
    adapter = TypeAdapter(IanaTimezone)
    assert adapter.validate_python("Europe/Rome") == "Europe/Rome"
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        adapter.validate_python("Mars/Olympus_Mons")


def test_constrained_inputs_and_complete_enums() -> None:
    assert TypeAdapter(Page).validate_python(1) == 1
    assert TypeAdapter(PageSize).validate_python(100) == 100
    assert TypeAdapter(MetricLimit).validate_python(500) == 500
    assert TypeAdapter(MetricOffset).validate_python(10_000) == 10_000

    for adapter, invalid in [
        (TypeAdapter(Page), 0),
        (TypeAdapter(PageSize), 101),
        (TypeAdapter(MetricLimit), 0),
        (TypeAdapter(MetricOffset), 10_001),
    ]:
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)

    metric_values = TypeAdapter(MetricType).json_schema()["enum"]
    assert metric_values == [
        "path",
        "fullPath",
        "entry",
        "exit",
        "referrer",
        "domain",
        "title",
        "query",
        "event",
        "tag",
        "hostname",
        "utmSource",
        "utmMedium",
        "utmCampaign",
        "utmContent",
        "utmTerm",
        "browser",
        "os",
        "device",
        "screen",
        "language",
        "country",
        "city",
        "region",
        "distinctId",
        "channel",
    ]


def test_filters_validate_uuids_and_serialize_upstream_aliases() -> None:
    value = "11111111-1111-4111-8111-111111111111"
    filters = Filters.model_validate(
        {
            "language": "it-IT",
            "event": "signup",
            "distinct_id": "visitor-1",
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "launch",
            "utm_content": "hero",
            "utm_term": "analytics",
            "segment": value,
            "cohort": value,
        }
    )

    assert filters.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "language": "it-IT",
        "event": "signup",
        "distinctId": "visitor-1",
        "utmSource": "newsletter",
        "utmMedium": "email",
        "utmCampaign": "launch",
        "utmContent": "hero",
        "utmTerm": "analytics",
        "segment": value,
        "cohort": value,
    }
    with pytest.raises(ValidationError):
        Filters.model_validate({"segment": "not-a-uuid"})


@pytest.mark.parametrize("origin", ["cloud_current", "self_hosted_v3"])
@pytest.mark.parametrize("filename", list(FIXTURE_MODELS))
def test_contract_fixtures_validate(origin: str, filename: str) -> None:
    payload = json.loads((FIXTURES / origin / filename).read_text())
    model = FIXTURE_MODELS[filename].validate_python(payload)
    serialized = FIXTURE_MODELS[filename].dump_python(model, mode="json", by_alias=True)
    assert serialized is not None


def test_extra_fields_are_preserved() -> None:
    payload = json.loads((FIXTURES / "cloud_current" / "active.json").read_text())
    active = ActiveVisitors.model_validate(payload)
    assert active.model_dump()["contractRevision"] == "current"


def test_structurally_incompatible_payload_is_rejected() -> None:
    with pytest.raises(ValidationError):
        WebsitePage.model_validate({"data": [], "count": 0})
    with pytest.raises(ValidationError):
        TypeAdapter(list[Metric | ExpandedMetric]).validate_python([{"unexpected": True}])
