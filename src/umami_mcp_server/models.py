from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, TypeAlias
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class UmamiModel(BaseModel):
    """Base model for additive Umami API responses."""

    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class WebsiteUser(UmamiModel):
    id: UUID
    username: str


class Website(UmamiModel):
    id: UUID
    name: str
    domain: str
    share_id: str | None = Field(default=None, alias="shareId")
    reset_at: datetime | None = Field(default=None, alias="resetAt")
    user_id: UUID | None = Field(default=None, alias="userId")
    team_id: UUID | None = Field(default=None, alias="teamId")
    created_by: UUID | None = Field(default=None, alias="createdBy")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    deleted_at: datetime | None = Field(default=None, alias="deletedAt")
    user: WebsiteUser | None = None


class WebsitePage(UmamiModel):
    data: list[Website]
    count: int
    page: int
    page_size: int = Field(alias="pageSize")


class StatsValues(UmamiModel):
    pageviews: int
    visitors: int
    visits: int
    bounces: int
    totaltime: int


class WebsiteStats(StatsValues):
    comparison: StatsValues


class TimeSeriesPoint(UmamiModel):
    x: datetime
    y: int


class PageviewsComparison(UmamiModel):
    pageviews: list[TimeSeriesPoint]
    sessions: list[TimeSeriesPoint]
    start_date: datetime | None = Field(default=None, alias="startDate")
    end_date: datetime | None = Field(default=None, alias="endDate")


class Pageviews(UmamiModel):
    pageviews: list[TimeSeriesPoint]
    sessions: list[TimeSeriesPoint]
    start_date: datetime | None = Field(default=None, alias="startDate")
    end_date: datetime | None = Field(default=None, alias="endDate")
    compare: PageviewsComparison | None = None


class Metric(UmamiModel):
    x: str
    y: int


class ExpandedMetric(UmamiModel):
    name: str
    pageviews: int
    visitors: int
    visits: int
    bounces: int
    totaltime: int


class ActiveVisitors(UmamiModel):
    visitors: int


WebsiteId: TypeAlias = Annotated[
    UUID,
    Field(description="UUID of the Umami website."),
]
Page: TypeAlias = Annotated[
    int,
    Field(ge=1, description="One-based result page number."),
]
PageSize: TypeAlias = Annotated[
    int,
    Field(ge=1, le=100, description="Number of websites per page (1-100)."),
]
MetricLimit: TypeAlias = Annotated[
    int,
    Field(ge=1, le=500, description="Maximum number of metric rows to return (1-500)."),
]
MetricOffset: TypeAlias = Annotated[
    int,
    Field(ge=0, le=10_000, description="Number of metric rows to skip (0-10000)."),
]
TimeUnit: TypeAlias = Annotated[
    Literal["minute", "hour", "day", "month", "year"],
    Field(description="Time bucket used for the pageview series."),
]
Comparison: TypeAlias = Annotated[
    Literal["prev", "yoy"] | None,
    Field(description="Compare with the previous period or the same period last year."),
]
MetricType: TypeAlias = Annotated[
    Literal[
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
    ],
    Field(description="Dimension to aggregate for the metrics response."),
]


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone must be a valid IANA timezone name") from error
    return value


IanaTimezone: TypeAlias = Annotated[
    str,
    Field(
        description="IANA timezone name used to bucket pageviews.",
        examples=["UTC", "Europe/Rome"],
    ),
    AfterValidator(_validate_timezone),
]


class Filters(BaseModel):
    """Documented filters accepted by Umami v3 analytics endpoints."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    path: str | None = None
    referrer: str | None = None
    title: str | None = None
    query: str | None = None
    browser: str | None = None
    os: str | None = None
    device: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    language: str | None = None
    hostname: str | None = None
    tag: str | None = None
    event: str | None = None
    distinct_id: str | None = Field(default=None, serialization_alias="distinctId")
    utm_source: str | None = Field(default=None, serialization_alias="utmSource")
    utm_medium: str | None = Field(default=None, serialization_alias="utmMedium")
    utm_campaign: str | None = Field(default=None, serialization_alias="utmCampaign")
    utm_content: str | None = Field(default=None, serialization_alias="utmContent")
    utm_term: str | None = Field(default=None, serialization_alias="utmTerm")
    segment: UUID | None = None
    cohort: UUID | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    return int(_as_utc(dt).timestamp() * 1000)


def ms_timerange(
    start_at: datetime | None,
    end_at: datetime | None,
    *,
    default_days: int = 7,
    _clock: Callable[[], datetime] = _utc_now,
) -> tuple[int, int]:
    now = _as_utc(_clock())
    end_dt = _as_utc(end_at) if end_at is not None else now
    start_dt = _as_utc(start_at) if start_at is not None else end_dt - timedelta(days=default_days)
    if end_dt <= start_dt:
        raise ValueError("end_at must be after start_at")
    return datetime_to_ms(start_dt), datetime_to_ms(end_dt)
