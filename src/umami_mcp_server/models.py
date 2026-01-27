from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel


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
) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    end_dt = _as_utc(end_at) if end_at is not None else now
    start_dt = _as_utc(start_at) if start_at is not None else end_dt - timedelta(days=default_days)
    if end_dt <= start_dt:
        raise ValueError("end_at must be after start_at")
    return datetime_to_ms(start_dt), datetime_to_ms(end_dt)


class Filters(BaseModel):
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
    hostname: str | None = None
    tag: str | None = None
    segment: str | None = None
    cohort: str | None = None
