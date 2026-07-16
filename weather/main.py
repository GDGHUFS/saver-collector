from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from api import DailyRequestLimitError, FatalWeatherApiError, WeatherApiClient
from config import BASE_DIR, CollectorSettings, load_settings
from grid import grid_to_latitude_longitude, latitude_longitude_to_grid
from locations import load_location_dataset
from models import GridPoint
from repository import WeatherRepository, connect
from schedule import KST, latest_available_issue, parse_issue_datetime


LOGGER = logging.getLogger("saver.weather")


@dataclass
class CollectionSummary:
    """전국 격자 한 발표본의 실행 집계다."""

    total_grids: int
    completed_grids: int = 0
    failed_grids: int = 0
    saved_values: int = 0
    skipped_items: int = 0
    response_pages: int = 0


def parse_args() -> argparse.Namespace:
    """전국 수집과 제한된 검증 실행을 위한 명령행 옵션을 파싱한다."""

    parser = argparse.ArgumentParser(description="SAVER nationwide weather collector")
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="수집 전에 weather/table.sql을 PostgreSQL에 적용한다.",
    )
    parser.add_argument(
        "--sync-locations",
        action="store_true",
        help="제공된 격자·위경도 XLSX를 DB에 전체 동기화한다.",
    )
    parser.add_argument(
        "--locations-only",
        action="store_true",
        help="위치 기준정보만 동기화하고 API는 호출하지 않는다.",
    )
    parser.add_argument(
        "--issue",
        help="수집할 발표시각(KST, YYYYMMDDHHMM). 생략하면 최신 선택 주기를 사용한다.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="이미 저장된 격자 발표본도 API에서 다시 받아 교체한다.",
    )
    parser.add_argument(
        "--grid",
        nargs=2,
        type=int,
        action="append",
        metavar=("NX", "NY"),
        help="특정 격자만 수집한다. 여러 번 지정할 수 있다.",
    )
    parser.add_argument(
        "--coordinate",
        nargs=2,
        type=float,
        action="append",
        metavar=("LATITUDE", "LONGITUDE"),
        help="특정 위경도의 격자만 수집한다. 여러 번 지정할 수 있다.",
    )
    parser.add_argument(
        "--region",
        action="append",
        help="지역명 토큰이 모두 일치하는 격자만 수집한다. 여러 번 지정할 수 있다.",
    )
    return parser.parse_args()


async def collect_grids(
    repository: WeatherRepository,
    api_client: WeatherApiClient,
    *,
    grids: tuple[GridPoint, ...],
    issued_at: datetime,
    concurrency: int,
    api_key: str,
) -> CollectionSummary:
    """격자별 실패를 격리하면서 한 발표본을 제한된 동시성으로 수집한다."""

    summary = CollectionSummary(total_grids=len(grids))
    semaphore = asyncio.Semaphore(concurrency)
    global_error_logged = False

    async def collect_one(grid: GridPoint) -> None:
        nonlocal global_error_logged
        async with semaphore:
            try:
                forecast = await api_client.fetch_forecast(grid, issued_at)
                saved_values = await repository.save_forecast(forecast)
            except Exception as exc:
                summary.failed_grids += 1
                message = str(exc).replace(api_key, "***") if api_key else str(exc)
                if isinstance(exc, (DailyRequestLimitError, FatalWeatherApiError)):
                    if not global_error_logged:
                        LOGGER.error("전체 격자 호출 중단: %s", message)
                        global_error_logged = True
                else:
                    LOGGER.error(
                        "격자 수집 실패: nx=%s, ny=%s, error_type=%s, error=%s",
                        grid.nx,
                        grid.ny,
                        type(exc).__name__,
                        message,
                    )
            else:
                summary.completed_grids += 1
                summary.saved_values += saved_values
                summary.skipped_items += forecast.skipped_items
                summary.response_pages += forecast.page_count
            finally:
                finished = summary.completed_grids + summary.failed_grids
                if finished % 100 == 0 or finished == summary.total_grids:
                    LOGGER.info(
                        "수집 진행: finished=%s/%s, succeeded=%s, failed=%s",
                        finished,
                        summary.total_grids,
                        summary.completed_grids,
                        summary.failed_grids,
                    )

    await asyncio.gather(*(collect_one(grid) for grid in grids))
    return summary


async def resolve_target_grids(
    repository: WeatherRepository,
    args: argparse.Namespace,
) -> tuple[GridPoint, ...]:
    """CLI 선택자가 없으면 전국 행정구역 격자, 있으면 선택 격자를 반환한다."""

    selected: dict[tuple[int, int], GridPoint] = {}
    for nx, ny in args.grid or []:
        grid = grid_to_latitude_longitude(nx, ny)
        selected[(grid.nx, grid.ny)] = grid
    for latitude, longitude in args.coordinate or []:
        grid = latitude_longitude_to_grid(latitude, longitude)
        selected[(grid.nx, grid.ny)] = grid
    for query in args.region or []:
        grids = await repository.search_region_grids(query)
        if not grids:
            raise ValueError(f"일치하는 지역이 없습니다: {query}")
        for grid in grids:
            selected[(grid.nx, grid.ny)] = grid

    if selected:
        return tuple(selected[key] for key in sorted(selected))
    return await repository.list_location_grids()


async def run_locked(
    repository: WeatherRepository,
    settings: CollectorSettings,
    args: argparse.Namespace,
) -> int:
    """잠금이 확보된 상태에서 위치 동기화, TTL 정리, 수집을 수행한다."""

    if args.sync_locations or args.locations_only:
        dataset = await asyncio.to_thread(
            load_location_dataset,
            settings.locations_path,
        )
        grid_count, location_count = await repository.sync_locations(dataset)
        LOGGER.info(
            "위치 기준정보 동기화 완료: grids=%s, locations=%s, source=%s",
            grid_count,
            location_count,
            settings.locations_path.name,
        )
    if args.locations_only:
        return 0

    now = datetime.now(KST)
    await repository.prune_api_usage(today=now.date())

    issued_at = (
        parse_issue_datetime(args.issue)
        if args.issue
        else latest_available_issue(
            now,
            settings.collection_hours,
            settings.availability_delay_minutes,
        )
    )
    available_at = issued_at + timedelta(
        minutes=settings.availability_delay_minutes
    )
    if available_at > now:
        raise ValueError(
            f"아직 제공 전인 발표본입니다: issued_at={issued_at.isoformat()}"
        )

    target_grids = await resolve_target_grids(repository, args)
    if not target_grids:
        raise RuntimeError(
            "수집할 전국 격자가 없습니다. 먼저 --sync-locations를 실행하세요."
        )

    if not args.force:
        collected_keys = await repository.list_collected_grid_keys(issued_at)
        target_grids = tuple(
            grid
            for grid in target_grids
            if (grid.nx, grid.ny) not in collected_keys
        )
    if not target_grids:
        await cleanup_expired_forecasts(repository, settings)
        LOGGER.info("이미 모든 대상 격자가 저장되었습니다: issued_at=%s", issued_at)
        return 0

    headers = {"User-Agent": settings.user_agent}
    async with httpx.AsyncClient(
        timeout=settings.http_timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        async def reserve_request() -> bool:
            return await repository.reserve_api_request(
                datetime.now(KST).date(),
                settings.daily_request_limit,
            )

        api_client = WeatherApiClient(
            client,
            settings,
            reserve_request=reserve_request,
        )
        summary = await collect_grids(
            repository,
            api_client,
            grids=target_grids,
            issued_at=issued_at,
            concurrency=settings.concurrency,
            api_key=settings.api_key or "",
        )

    await cleanup_expired_forecasts(repository, settings)
    LOGGER.info(
        "단기예보 수집 종료: issued_at=%s, target_grids=%s, "
        "completed_grids=%s, failed_grids=%s, saved_values=%s, "
        "skipped_items=%s, response_pages=%s",
        issued_at,
        summary.total_grids,
        summary.completed_grids,
        summary.failed_grids,
        summary.saved_values,
        summary.skipped_items,
        summary.response_pages,
    )
    return 1 if summary.failed_grids else 0


async def cleanup_expired_forecasts(
    repository: WeatherRepository,
    settings: CollectorSettings,
) -> None:
    """새 발표본 처리 뒤 TTL을 적용해 수집 중 fallback 공백을 피한다."""

    pruned_issues = await repository.prune_expired(
        now=datetime.now(KST),
        retention_days=settings.retention_days,
    )
    LOGGER.info(
        "만료 발표본 정리 완료: retention_days=%s, deleted_issues=%s",
        settings.retention_days,
        pruned_issues,
    )


async def async_main() -> int:
    """수집기 설정과 DB 수명주기를 관리한다."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args()
    settings = load_settings(require_api_key=not args.locations_only)

    pool = await connect(settings.database)
    try:
        repository = WeatherRepository(pool)
        if args.apply_schema:
            await repository.apply_schema(BASE_DIR / "table.sql")

        async with repository.collector_lock() as acquired:
            if not acquired:
                LOGGER.info("다른 weather 수집기가 실행 중이므로 이번 실행을 건너뜁니다.")
                return 0
            return await run_locked(repository, settings, args)
    finally:
        await pool.close()


def main() -> int:
    """비동기 수집기를 실행한다."""

    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
