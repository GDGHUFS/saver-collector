from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import dotenv


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

DEFAULT_BASE_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService"


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL 접속에 필요한 환경 변수 값을 보관한다."""

    host: str
    port: int
    user: str
    password: str
    dbname: str
    connect_timeout: float


@dataclass(frozen=True)
class AnniversaryOperation:
    """특일 정보제공 서비스의 조회 오퍼레이션을 표현한다."""

    name: str
    label: str


@dataclass(frozen=True)
class CollectorSettings:
    """수집기 실행 중 공유되는 설정 값 모음이다."""

    database: DatabaseSettings
    api_key: str
    base_url: str
    operations: tuple[AnniversaryOperation, ...]
    http_timeout: float
    user_agent: str
    num_of_rows: int


def load_settings() -> CollectorSettings:
    """루트 `.env`를 읽고 특일 수집기에 필요한 설정 객체를 만든다."""

    dotenv.load_dotenv(ROOT_DIR / ".env")
    api_key = os.getenv("ANNIVERSARY_API_KEY")
    if not api_key:
        raise RuntimeError("ANNIVERSARY_API_KEY is not set")

    return CollectorSettings(
        database=DatabaseSettings(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "saver"),
            password=os.getenv("POSTGRES_PASSWORD", "saver"),
            dbname=os.getenv("POSTGRES_DB", "saverdb"),
            connect_timeout=float(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
        ),
        api_key=api_key,
        base_url=os.getenv("ANNIVERSARY_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        operations=(
            AnniversaryOperation("getHoliDeInfo", "국경일"),
            AnniversaryOperation("getRestDeInfo", "공휴일"),
            AnniversaryOperation("getAnniversaryInfo", "기념일"),
            AnniversaryOperation("get24DivisionsInfo", "24절기"),
            AnniversaryOperation("getSundryDayInfo", "잡절"),
        ),
        http_timeout=float(os.getenv("ANNIVERSARY_HTTP_TIMEOUT", "10")),
        user_agent=os.getenv("ANNIVERSARY_USER_AGENT", "SAVER-Collector/1.0"),
        num_of_rows=int(os.getenv("ANNIVERSARY_NUM_OF_ROWS", "100")),
    )
