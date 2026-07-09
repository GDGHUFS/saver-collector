from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import NamedTuple

import httpx

from config import BASE_DIR, RssSource, load_settings
from parser import parse_rss
from repository import RssRepository, connect


LOGGER = logging.getLogger("saver.rss")


class CollectResult(NamedTuple):
    """공급자 하나의 저장 및 제외 결과를 나타낸다."""

    saved_items: int
    skipped_items: int


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 파싱해 실행 모드를 결정한다."""

    parser = argparse.ArgumentParser(description="SAVER RSS collector")
    parser.add_argument(
        "--samples",
        action="store_true",
        help="원격 RSS 대신 저장소의 샘플 RSS 파일을 사용한다.",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="수집 전에 rss/table.sql을 PostgreSQL에 적용한다.",
    )
    return parser.parse_args()


async def fetch_remote_xml(source_url: str, *, timeout: float, user_agent: str) -> str:
    """원격 RSS URL을 timeout과 User-Agent를 지정해 가져온다."""

    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = await client.get(source_url)
        response.raise_for_status()
        return response.text


def read_sample_xml(path: Path) -> str:
    """검증과 로컬 개발을 위해 저장소에 포함된 샘플 RSS를 읽는다."""

    return path.read_text(encoding="utf-8")


async def collect_source(
    repository: RssRepository,
    *,
    source: RssSource,
    use_sample: bool,
    timeout: float,
    user_agent: str,
) -> CollectResult:
    """공급자 하나의 RSS를 가져와 파싱하고 DB에 저장한다."""

    if use_sample:
        xml_text = read_sample_xml(source.sample_path)
    else:
        xml_text = await fetch_remote_xml(
            source.feed_url,
            timeout=timeout,
            user_agent=user_agent,
        )

    parsed = parse_rss(xml_text, feed_url=source.feed_url, publisher=source.publisher)
    _, item_count = await repository.save(parsed)
    return CollectResult(saved_items=item_count, skipped_items=parsed.skipped_items)


async def async_main() -> int:
    """RSS 공급자들을 순회하며 실패한 공급자는 로그로 남기고 다음 작업을 계속한다."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args()
    settings = load_settings()

    saved_total = 0
    skipped_total = 0
    failed_sources = 0

    connection = await connect(settings.database)
    try:
        repository = RssRepository(connection)
        if args.apply_schema:
            await repository.apply_schema(BASE_DIR / "table.sql")

        for source in settings.sources:
            try:
                result = await collect_source(
                    repository,
                    source=source,
                    use_sample=args.samples,
                    timeout=settings.http_timeout,
                    user_agent=settings.user_agent,
                )
            except Exception:
                failed_sources += 1
                LOGGER.exception("RSS 수집 실패: %s", source.publisher)
                continue

            saved_total += result.saved_items
            skipped_total += result.skipped_items
            LOGGER.info(
                "RSS 수집 완료: %s, saved_items=%s, skipped_items=%s",
                source.publisher,
                result.saved_items,
                result.skipped_items,
            )

        LOGGER.info(
            "RSS 전체 수집 종료: saved_items=%s, skipped_items=%s, failed_sources=%s",
            saved_total,
            skipped_total,
            failed_sources,
        )
        return 1 if failed_sources else 0
    finally:
        await connection.close()


def main() -> int:
    """비동기 수집기 실행을 위한 동기 진입점이다."""

    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
