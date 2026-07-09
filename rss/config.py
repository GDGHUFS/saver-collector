from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import dotenv


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent


@dataclass(frozen=True)
class DatabaseSettings:
    """PostgreSQL 접속에 필요한 환경 변수 값을 보관한다."""

    host: str
    port: int
    user: str
    password: str
    dbname: str


@dataclass(frozen=True)
class RssSource:
    """RSS 공급자의 표시 이름, 원본 URL, 로컬 샘플 파일을 묶는다."""

    publisher: str
    feed_url: str
    sample_path: Path


@dataclass(frozen=True)
class CollectorSettings:
    """수집기 실행 중 공유되는 설정 값 모음이다."""

    database: DatabaseSettings
    sources: tuple[RssSource, ...]
    http_timeout: float
    user_agent: str


def load_settings() -> CollectorSettings:
    """루트 `.env`를 읽고 RSS 수집기에 필요한 설정 객체를 만든다."""

    dotenv.load_dotenv(ROOT_DIR / ".env")
    return CollectorSettings(
        database=DatabaseSettings(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "saver"),
            password=os.getenv("POSTGRES_PASSWORD", "saver"),
            dbname=os.getenv("POSTGRES_DB", "saverdb"),
        ),
        sources=(
            RssSource(
                publisher="교수신문",
                feed_url="https://www.kyosu.net/rss/allArticle.xml",
                sample_path=BASE_DIR / "교수신문.xml",
            ),
            RssSource(
                publisher="전자신문",
                feed_url="http://rss.etnews.com/Section901.xml",
                sample_path=BASE_DIR / "전자신문.xml",
            ),
            RssSource(
                publisher="Hacker News",
                feed_url="https://news.ycombinator.com/rss",
                sample_path=BASE_DIR / "hackernews.rss",
            ),
        ),
        http_timeout=float(os.getenv("RSS_HTTP_TIMEOUT", "10")),
        user_agent=os.getenv("RSS_USER_AGENT", "SAVER-Collector/1.0"),
    )
