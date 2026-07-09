from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asyncpg
from asyncpg import Connection

from config import DatabaseSettings
from parser import Category, ParsedFeed, ParsedItem, ParsedRss


class RssRepository:
    """RSS 파싱 결과를 PostgreSQL 테이블에 비동기로 저장하는 저장소다."""

    def __init__(self, connection: Connection):
        self.connection = connection

    async def apply_schema(self, schema_path: Path) -> None:
        """`table.sql`을 현재 DB에 적용한다."""

        await self.connection.execute(schema_path.read_text(encoding="utf-8"))

    async def save(self, rss: ParsedRss) -> tuple[int, int]:
        """피드 메타데이터와 기사 목록을 트랜잭션 안에서 upsert한다."""

        async with self.connection.transaction():
            feed_id = await self._upsert_feed(rss.feed)
            await self._replace_feed_categories(feed_id, rss.feed.categories)

            saved_items = 0
            for item in rss.items:
                item_id = await self._upsert_item(feed_id, item)
                if item_id is None:
                    continue
                await self._replace_item_categories(item_id, item.categories)
                saved_items += 1

        return feed_id, saved_items

    async def _upsert_feed(self, feed: ParsedFeed) -> int:
        """feed_url 기준으로 채널 메타데이터를 삽입하거나 갱신한다."""

        return await self.connection.fetchval(
            """
            INSERT INTO news_feeds (
                feed_url, publisher, title, link, description, language,
                copyright, managing_editor, web_master, pub_date,
                last_build_date, generator, docs, cloud, ttl, image, rating,
                text_input, skip_hours, skip_days, extensions
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14::jsonb, $15, $16::jsonb, $17,
                $18::jsonb, $19::smallint[], $20::text[], $21::jsonb
            )
            ON CONFLICT (feed_url) DO UPDATE SET
                publisher = EXCLUDED.publisher,
                title = EXCLUDED.title,
                link = EXCLUDED.link,
                description = EXCLUDED.description,
                language = EXCLUDED.language,
                copyright = EXCLUDED.copyright,
                managing_editor = EXCLUDED.managing_editor,
                web_master = EXCLUDED.web_master,
                pub_date = EXCLUDED.pub_date,
                last_build_date = EXCLUDED.last_build_date,
                generator = EXCLUDED.generator,
                docs = EXCLUDED.docs,
                cloud = EXCLUDED.cloud,
                ttl = EXCLUDED.ttl,
                image = EXCLUDED.image,
                rating = EXCLUDED.rating,
                text_input = EXCLUDED.text_input,
                skip_hours = EXCLUDED.skip_hours,
                skip_days = EXCLUDED.skip_days,
                extensions = EXCLUDED.extensions,
                updated_at = NOW()
            RETURNING id
            """,
            feed.feed_url,
            feed.publisher,
            feed.title,
            feed.link,
            feed.description,
            feed.language,
            feed.copyright,
            feed.managing_editor,
            feed.web_master,
            feed.pub_date,
            feed.last_build_date,
            feed.generator,
            feed.docs,
            _jsonb(feed.cloud),
            feed.ttl,
            _jsonb(feed.image),
            feed.rating,
            _jsonb(feed.text_input),
            feed.skip_hours,
            feed.skip_days,
            _jsonb(feed.extensions),
        )

    async def _replace_feed_categories(self, feed_id: int, categories: list[Category]) -> None:
        """피드 카테고리는 최신 RSS 상태에 맞춰 삭제 후 다시 넣는다."""

        await self.connection.execute(
            "DELETE FROM news_feed_categories WHERE feed_id = $1",
            feed_id,
        )
        await self._insert_categories(
            "news_feed_categories",
            "feed_id",
            feed_id,
            categories,
        )

    async def _upsert_item(self, feed_id: int, item: ParsedItem) -> int | None:
        """guid 또는 link 기준으로 기사 항목을 삽입하거나 갱신한다."""

        if not item.title or not item.link:
            return None
        if item.guid:
            return await self._upsert_item_with_conflict(
                feed_id,
                item,
                "ON CONFLICT (feed_id, guid) WHERE guid IS NOT NULL",
            )
        return await self._upsert_item_with_conflict(
            feed_id,
            item,
            "ON CONFLICT (feed_id, link) WHERE guid IS NULL AND link IS NOT NULL",
        )

    async def _upsert_item_with_conflict(
        self,
        feed_id: int,
        item: ParsedItem,
        conflict: str,
    ) -> int:
        """전달받은 partial unique index 조건에 맞춰 news_items를 upsert한다."""

        return await self.connection.fetchval(
            f"""
            INSERT INTO news_items (
                feed_id, title, link, description, author, comments,
                enclosure_url, enclosure_length, enclosure_type, guid,
                guid_is_permalink, pub_date, source_name, source_url,
                extensions
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15::jsonb
            )
            {conflict} DO UPDATE SET
                title = EXCLUDED.title,
                link = EXCLUDED.link,
                description = EXCLUDED.description,
                author = EXCLUDED.author,
                comments = EXCLUDED.comments,
                enclosure_url = EXCLUDED.enclosure_url,
                enclosure_length = EXCLUDED.enclosure_length,
                enclosure_type = EXCLUDED.enclosure_type,
                guid_is_permalink = EXCLUDED.guid_is_permalink,
                pub_date = EXCLUDED.pub_date,
                source_name = EXCLUDED.source_name,
                source_url = EXCLUDED.source_url,
                extensions = EXCLUDED.extensions,
                updated_at = NOW()
            RETURNING id
            """,
            feed_id,
            item.title,
            item.link,
            item.description,
            item.author,
            item.comments,
            item.enclosure_url,
            item.enclosure_length,
            item.enclosure_type,
            item.guid,
            item.guid_is_permalink,
            item.pub_date,
            item.source_name,
            item.source_url,
            _jsonb(item.extensions),
        )

    async def _replace_item_categories(self, item_id: int, categories: list[Category]) -> None:
        """기사 카테고리는 최신 RSS 상태에 맞춰 삭제 후 다시 넣는다."""

        await self.connection.execute(
            "DELETE FROM news_item_categories WHERE item_id = $1",
            item_id,
        )
        await self._insert_categories(
            "news_item_categories",
            "item_id",
            item_id,
            categories,
        )

    async def _insert_categories(
        self,
        table: str,
        id_column: str,
        owner_id: int,
        categories: list[Category],
    ) -> None:
        """카테고리 목록을 피드 또는 기사 카테고리 테이블에 bulk insert한다."""

        if not categories:
            return

        rows = [(owner_id, category.name, category.domain) for category in categories]
        await self.connection.executemany(
            f"INSERT INTO {table} ({id_column}, name, domain) VALUES ($1, $2, $3)",
            rows,
        )


async def connect(settings: DatabaseSettings) -> Connection:
    """환경 변수로 구성한 PostgreSQL 연결을 비동기로 생성한다."""

    return await asyncpg.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.dbname,
    )


def _jsonb(value: Any) -> str | None:
    """asyncpg에 JSONB 값을 넘기기 위해 JSON 문자열로 직렬화한다."""

    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)
