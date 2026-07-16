from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class GridPoint:
    """기상청 단기예보 격자와 격자 중심 위경도를 나타낸다."""

    nx: int
    ny: int
    longitude: float
    latitude: float


@dataclass(frozen=True)
class WeatherLocation:
    """행정구역 이름과 단기예보 격자의 매핑을 나타낸다."""

    administrative_code: str
    region_level_1: str
    region_level_2: str | None
    region_level_3: str | None
    nx: int
    ny: int
    longitude: float | None
    latitude: float | None
    source_updated_on: date | None


@dataclass(frozen=True)
class ForecastValue:
    """단기예보 응답 item 하나를 정규화한 값이다."""

    issued_at: datetime
    forecast_at: datetime
    nx: int
    ny: int
    category: str
    value: str


@dataclass(frozen=True)
class FetchedForecast:
    """한 격자와 발표시각의 전체 페이지 수집 결과다."""

    grid: GridPoint
    issued_at: datetime
    values: tuple[ForecastValue, ...]
    total_count: int
    skipped_items: int
    page_count: int
