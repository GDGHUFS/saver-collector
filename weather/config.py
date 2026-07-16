from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import dotenv


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

ALL_ISSUE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)
DEFAULT_COLLECTION_HOURS = (2, 8, 14, 20)
DEFAULT_BASE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL 연결 풀 설정이다."""

    host: str
    port: int
    user: str
    password: str
    dbname: str
    connect_timeout: float
    pool_size: int


@dataclass(frozen=True)
class CollectorSettings:
    """전국 단기예보 수집에 필요한 설정 모음이다."""

    database: DatabaseSettings
    api_key: str | None
    base_url: str
    http_timeout: float
    user_agent: str
    num_of_rows: int
    concurrency: int
    requests_per_second: float
    daily_request_limit: int
    max_attempts: int
    retry_base_delay: float
    retention_days: int
    collection_hours: tuple[int, ...]
    availability_delay_minutes: int
    locations_path: Path


def load_settings(*, require_api_key: bool = True) -> CollectorSettings:
    """루트 `.env`와 실행 환경에서 설정을 읽고 검증한다."""

    dotenv.load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("WEATHER_API_KEY")
    if require_api_key and not api_key:
        raise RuntimeError("WEATHER_API_KEY is not set")

    settings = CollectorSettings(
        database=DatabaseSettings(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=_positive_int("POSTGRES_PORT", "5432"),
            user=os.getenv("POSTGRES_USER", "saver"),
            password=os.getenv("POSTGRES_PASSWORD", "saver"),
            dbname=os.getenv("POSTGRES_DB", "saverdb"),
            connect_timeout=_positive_float("POSTGRES_CONNECT_TIMEOUT", "10"),
            pool_size=_positive_int("WEATHER_DB_POOL_SIZE", "4"),
        ),
        api_key=api_key,
        base_url=os.getenv("WEATHER_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        http_timeout=_positive_float("WEATHER_HTTP_TIMEOUT", "15"),
        user_agent=os.getenv("WEATHER_USER_AGENT", "SAVER-Collector/1.0"),
        num_of_rows=_positive_int("WEATHER_NUM_OF_ROWS", "1000"),
        concurrency=_positive_int("WEATHER_CONCURRENCY", "10"),
        requests_per_second=_positive_float("WEATHER_REQUESTS_PER_SECOND", "20"),
        daily_request_limit=_positive_int("WEATHER_DAILY_REQUEST_LIMIT", "9500"),
        max_attempts=_positive_int("WEATHER_MAX_ATTEMPTS", "3"),
        retry_base_delay=_positive_float("WEATHER_RETRY_BASE_DELAY", "1"),
        retention_days=_positive_int("WEATHER_RETENTION_DAYS", "1"),
        collection_hours=_parse_collection_hours(
            os.getenv(
                "WEATHER_COLLECTION_HOURS",
                ",".join(str(hour) for hour in DEFAULT_COLLECTION_HOURS),
            )
        ),
        availability_delay_minutes=_non_negative_int(
            "WEATHER_AVAILABILITY_DELAY_MINUTES", "10"
        ),
        locations_path=_locations_path(),
    )
    if settings.database.pool_size < 2:
        raise ValueError("WEATHER_DB_POOL_SIZE는 수집 잠금을 위해 2 이상이어야 합니다.")
    if not 1000 <= settings.num_of_rows <= 9999:
        raise ValueError(
            "WEATHER_NUM_OF_ROWS는 전국 수집 호출량을 위해 1000 이상 9999 이하여야 합니다."
        )
    if settings.requests_per_second > 30:
        raise ValueError("WEATHER_REQUESTS_PER_SECOND는 API 제한인 30 이하여야 합니다.")
    return settings


def _locations_path() -> Path:
    raw_path = os.getenv("WEATHER_LOCATIONS_PATH")
    if raw_path:
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else ROOT_DIR / path

    matches = sorted(BASE_DIR.glob("*격자_위경도*.xlsx"))
    if not matches:
        return BASE_DIR / "weather_locations.xlsx"
    return matches[-1]


def _parse_collection_hours(raw_value: str) -> tuple[int, ...]:
    try:
        hours = tuple(dict.fromkeys(int(value.strip()) for value in raw_value.split(",")))
    except ValueError as exc:
        raise ValueError("WEATHER_COLLECTION_HOURS는 쉼표로 구분한 정시여야 합니다.") from exc
    if not hours or any(hour not in ALL_ISSUE_HOURS for hour in hours):
        allowed = ", ".join(f"{hour:02d}" for hour in ALL_ISSUE_HOURS)
        raise ValueError(f"발표시각은 다음 값만 허용합니다: {allowed}")
    return tuple(sorted(hours))


def _positive_int(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name}은 0보다 커야 합니다.")
    return value


def _non_negative_int(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value < 0:
        raise ValueError(f"{name}은 0 이상이어야 합니다.")
    return value


def _positive_float(name: str, default: str) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name}은 0보다 커야 합니다.")
    return value
