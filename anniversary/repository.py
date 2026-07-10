from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
from asyncpg import Connection

from config import DatabaseSettings
from parser import SpecialDay


class AnniversaryRepository:
    """특일 항목을 PostgreSQL에 저장하는 저장소다."""

    def __init__(self, connection: Connection):
        self.connection = connection

    async def apply_schema(self, schema_path: Path) -> None:
        """`table.sql`을 현재 DB에 적용한다."""

        await self.connection.execute(schema_path.read_text(encoding="utf-8"))

    async def save_days(self, days: list[SpecialDay]) -> int:
        """특일 항목 목록을 upsert하고 저장 개수를 반환한다."""

        if not days:
            return 0

        rows = [
            (
                day.observed_date,
                day.date_kind,
                day.date_name,
                day.is_holiday,
            )
            for day in days
        ]

        async with self.connection.transaction():
            await self.connection.executemany(
                """
                INSERT INTO anniversary_special_days (
                    observed_date, date_kind, date_name, is_holiday
                )
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (observed_date, date_kind, date_name)
                DO UPDATE SET
                    is_holiday = EXCLUDED.is_holiday,
                    updated_at = NOW()
                """,
                rows,
            )

        return len(rows)


async def connect(settings: DatabaseSettings) -> Connection:
    """환경 변수로 구성한 PostgreSQL 연결을 비동기로 생성한다."""

    return await asyncio.wait_for(
        asyncpg.connect(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.dbname,
            timeout=settings.connect_timeout,
        ),
        timeout=settings.connect_timeout,
    )
