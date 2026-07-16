from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

import asyncpg

from config import DatabaseSettings
from locations import LocationDataset
from models import FetchedForecast, GridPoint


REGION_ALIASES = {
    "강원도": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "전라북도": "전북특별자치도",
    "전남": "전라남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주도": "제주특별자치도",
    "세종시": "세종특별자치시",
}

CATEGORY_COLUMNS = {
    "POP": "precipitation_probability",
    "PTY": "precipitation_type",
    "PCP": "precipitation_amount",
    "REH": "humidity",
    "SNO": "snowfall_amount",
    "SKY": "sky_status",
    "TMP": "temperature",
    "TMN": "minimum_temperature",
    "TMX": "maximum_temperature",
    "UUU": "wind_u_component",
    "VVV": "wind_v_component",
    "WAV": "wave_height",
    "VEC": "wind_direction",
    "WSD": "wind_speed",
}
CATEGORY_ORDER = tuple(CATEGORY_COLUMNS)
FORECAST_COLUMNS = tuple(CATEGORY_COLUMNS[category] for category in CATEGORY_ORDER)


class WeatherRepository:
    """위치 기준정보와 단기예보 발표본을 PostgreSQL에 저장한다."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def apply_schema(self, schema_path: Path) -> None:
        """`table.sql`을 현재 DB에 적용한다."""

        async with self.pool.acquire() as connection:
            await connection.execute(schema_path.read_text(encoding="utf-8"))

    @asynccontextmanager
    async def collector_lock(self) -> AsyncIterator[bool]:
        """동일 DB에서 전국 수집기가 중복 실행되지 않도록 잠근다."""

        async with self.pool.acquire() as connection:
            acquired = await connection.fetchval(
                "SELECT pg_try_advisory_lock($1, $2)",
                1360000,
                41,
            )
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    await connection.execute(
                        "SELECT pg_advisory_unlock($1, $2)",
                        1360000,
                        41,
                    )

    async def sync_locations(self, dataset: LocationDataset) -> tuple[int, int]:
        """위치 파일을 고유 격자 upsert와 행정구역 전체 동기화로 적용한다."""

        grid_rows = [
            (grid.nx, grid.ny, grid.longitude, grid.latitude)
            for grid in dataset.grid_points
        ]
        location_rows = [
            (
                location.administrative_code,
                location.region_level_1,
                location.region_level_2,
                location.region_level_3,
                location.nx,
                location.ny,
                location.longitude,
                location.latitude,
                location.source_updated_on,
            )
            for location in dataset.locations
        ]

        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    CREATE TEMPORARY TABLE weather_grid_points_stage (
                        nx SMALLINT NOT NULL,
                        ny SMALLINT NOT NULL,
                        longitude DOUBLE PRECISION NOT NULL,
                        latitude DOUBLE PRECISION NOT NULL
                    ) ON COMMIT DROP
                    """
                )
                await connection.copy_records_to_table(
                    "weather_grid_points_stage",
                    records=grid_rows,
                    columns=("nx", "ny", "longitude", "latitude"),
                )
                await connection.execute(
                    """
                    INSERT INTO weather_grid_points (nx, ny, longitude, latitude)
                    SELECT nx, ny, longitude, latitude
                    FROM weather_grid_points_stage
                    ON CONFLICT (nx, ny) DO UPDATE SET
                        longitude = EXCLUDED.longitude,
                        latitude = EXCLUDED.latitude,
                        updated_at = NOW()
                    """
                )
                await connection.execute("DELETE FROM weather_locations")
                await connection.copy_records_to_table(
                    "weather_locations",
                    records=location_rows,
                    columns=(
                        "administrative_code",
                        "region_level_1",
                        "region_level_2",
                        "region_level_3",
                        "nx",
                        "ny",
                        "longitude",
                        "latitude",
                        "source_updated_on",
                    ),
                )

        return len(grid_rows), len(location_rows)

    async def list_location_grids(self) -> tuple[GridPoint, ...]:
        """행정구역 파일에서 사용하는 전국 고유 격자를 반환한다."""

        async with self.pool.acquire() as connection:
            records = await connection.fetch(
                """
                SELECT DISTINCT gp.nx, gp.ny, gp.longitude, gp.latitude
                FROM weather_locations AS location
                JOIN weather_grid_points AS gp
                  ON gp.nx = location.nx AND gp.ny = location.ny
                ORDER BY gp.nx, gp.ny
                """
            )
        return tuple(_record_to_grid(record) for record in records)

    async def search_region_grids(self, query: str) -> tuple[GridPoint, ...]:
        """공백으로 나눈 지역명 토큰이 모두 일치하는 고유 격자를 찾는다."""

        tokens = [REGION_ALIASES.get(token, token) for token in query.split() if token]
        if not tokens:
            return ()
        patterns = [f"%{_escape_like(token)}%" for token in tokens]
        async with self.pool.acquire() as connection:
            records = await connection.fetch(
                """
                SELECT DISTINCT gp.nx, gp.ny, gp.longitude, gp.latitude
                FROM weather_locations AS location
                JOIN weather_grid_points AS gp
                  ON gp.nx = location.nx AND gp.ny = location.ny
                WHERE concat_ws(
                    ' ',
                    location.region_level_1,
                    location.region_level_2,
                    location.region_level_3
                ) ILIKE ALL($1::text[])
                ORDER BY gp.nx, gp.ny
                """,
                patterns,
            )
        return tuple(_record_to_grid(record) for record in records)

    async def list_collected_grid_keys(
        self,
        issued_at: datetime,
    ) -> set[tuple[int, int]]:
        """지정 발표본이 이미 저장된 격자 키를 반환한다."""

        async with self.pool.acquire() as connection:
            records = await connection.fetch(
                """
                SELECT nx, ny
                FROM weather_forecast_issues
                WHERE issued_at = $1
                """,
                issued_at,
            )
        return {(record["nx"], record["ny"]) for record in records}

    async def save_forecast(self, forecast: FetchedForecast) -> int:
        """완성된 발표본을 트랜잭션 안에서 스냅샷 교체한다."""

        if not forecast.values:
            raise ValueError("저장할 단기예보 값이 없습니다.")
        for value in forecast.values:
            if (
                value.nx != forecast.grid.nx
                or value.ny != forecast.grid.ny
                or value.issued_at != forecast.issued_at
            ):
                raise ValueError("발표본에 다른 격자 또는 발표시각의 값이 섞였습니다.")

        async with self.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO weather_grid_points (
                        nx, ny, longitude, latitude
                    )
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (nx, ny) DO UPDATE SET
                        longitude = EXCLUDED.longitude,
                        latitude = EXCLUDED.latitude,
                        updated_at = NOW()
                    """,
                    forecast.grid.nx,
                    forecast.grid.ny,
                    forecast.grid.longitude,
                    forecast.grid.latitude,
                )
                issue_id = await connection.fetchval(
                    """
                    INSERT INTO weather_forecast_issues (nx, ny, issued_at)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (nx, ny, issued_at) DO UPDATE SET
                        updated_at = NOW()
                    RETURNING id
                    """,
                    forecast.grid.nx,
                    forecast.grid.ny,
                    forecast.issued_at,
                )
                await connection.execute(
                    """
                    DELETE FROM weather_forecasts
                    WHERE forecast_issue_id = $1
                    """,
                    issue_id,
                )
                forecast_rows: dict[datetime, dict[str, str]] = {}
                for value in forecast.values:
                    forecast_rows.setdefault(value.forecast_at, {})[
                        value.category
                    ] = value.value
                await connection.copy_records_to_table(
                    "weather_forecasts",
                    records=[
                        (
                            issue_id,
                            forecast_at,
                            *(
                                values_by_category.get(category)
                                for category in CATEGORY_ORDER
                            ),
                        )
                        for forecast_at, values_by_category in sorted(
                            forecast_rows.items()
                        )
                    ],
                    columns=(
                        "forecast_issue_id",
                        "forecast_at",
                        *FORECAST_COLUMNS,
                    ),
                )
                await connection.execute(
                    """
                    DELETE FROM weather_forecast_issues
                    WHERE nx = $1
                      AND ny = $2
                      AND issued_at < $3
                    """,
                    forecast.grid.nx,
                    forecast.grid.ny,
                    forecast.issued_at,
                )

        return len(forecast.values)

    async def reserve_api_request(self, usage_date: date, limit: int) -> bool:
        """일일 한도 안에서 실제 HTTP 요청 한 건을 원자적으로 예약한다."""

        async with self.pool.acquire() as connection:
            count = await connection.fetchval(
                """
                INSERT INTO weather_api_daily_usage (usage_date, request_count)
                VALUES ($1, 1)
                ON CONFLICT (usage_date) DO UPDATE SET
                    request_count = weather_api_daily_usage.request_count + 1,
                    updated_at = NOW()
                WHERE weather_api_daily_usage.request_count < $2
                RETURNING request_count
                """,
                usage_date,
                limit,
            )
        return count is not None

    async def prune_expired(self, *, now: datetime, retention_days: int) -> int:
        """보관기간이 지난 발표본을 삭제하고 cascade로 예보값도 정리한다."""

        cutoff = now - timedelta(days=retention_days)
        async with self.pool.acquire() as connection:
            status = await connection.execute(
                "DELETE FROM weather_forecast_issues WHERE issued_at < $1",
                cutoff,
            )
        return int(status.rsplit(" ", 1)[-1])

    async def prune_api_usage(self, *, today: date, retention_days: int = 30) -> int:
        """오래된 일일 API 사용량 운영 메타데이터를 정리한다."""

        cutoff = today - timedelta(days=retention_days)
        async with self.pool.acquire() as connection:
            status = await connection.execute(
                "DELETE FROM weather_api_daily_usage WHERE usage_date < $1",
                cutoff,
            )
        return int(status.rsplit(" ", 1)[-1])


async def connect(settings: DatabaseSettings) -> asyncpg.Pool:
    """환경 변수로 구성한 PostgreSQL 연결 풀을 생성한다."""

    return await asyncio.wait_for(
        asyncpg.create_pool(
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            database=settings.dbname,
            min_size=1,
            max_size=settings.pool_size,
            timeout=settings.connect_timeout,
        ),
        timeout=settings.connect_timeout,
    )


def _record_to_grid(record: asyncpg.Record) -> GridPoint:
    return GridPoint(
        nx=record["nx"],
        ny=record["ny"],
        longitude=record["longitude"],
        latitude=record["latitude"],
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
