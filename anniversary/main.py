from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date
from typing import NamedTuple
from urllib.parse import urlencode

import httpx

from config import BASE_DIR, AnniversaryOperation, load_settings
from parser import ParsedResponse, parse_special_day_response
from repository import AnniversaryRepository, connect


LOGGER = logging.getLogger("saver.anniversary")


class CollectResult(NamedTuple):
    """오퍼레이션과 월 하나의 수집 결과를 나타낸다."""

    saved_items: int
    skipped_items: int
    total_count: int


def parse_args() -> argparse.Namespace:
    """명령행 옵션을 파싱해 실행 모드를 결정한다."""

    today = date.today()
    parser = argparse.ArgumentParser(description="SAVER anniversary collector")
    parser.add_argument(
        "--year",
        type=int,
        default=today.year,
        help="수집할 연도. 기본값은 현재 연도다.",
    )
    parser.add_argument(
        "--month",
        type=int,
        choices=range(1, 13),
        action="append",
        help="수집할 월. 여러 번 지정할 수 있으며 생략하면 1월부터 12월까지 수집한다.",
    )
    parser.add_argument(
        "--operation",
        action="append",
        help="수집할 API 오퍼레이션명. 여러 번 지정할 수 있으며 생략하면 전체 오퍼레이션을 수집한다.",
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="수집 전에 anniversary/table.sql을 PostgreSQL에 적용한다.",
    )
    return parser.parse_args()


async def fetch_operation_month(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    operation: str,
    year: int,
    month: int,
    num_of_rows: int,
) -> ParsedResponse:
    """특일 API 오퍼레이션을 연월 단위로 호출하고 모든 페이지 응답을 합친다."""

    page_no = 1
    items = []
    skipped_items = 0
    total_count = 0

    while True:
        parsed = await fetch_operation_month_page(
            client,
            base_url=base_url,
            api_key=api_key,
            operation=operation,
            year=year,
            month=month,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )
        if parsed.result_code != "00":
            return parsed

        items.extend(parsed.items)
        skipped_items += parsed.skipped_items
        total_count = parsed.total_count
        if page_no * num_of_rows >= total_count:
            return ParsedResponse(
                result_code=parsed.result_code,
                result_msg=parsed.result_msg,
                items=items,
                total_count=total_count,
                skipped_items=skipped_items,
            )

        page_no += 1


async def fetch_operation_month_page(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    operation: str,
    year: int,
    month: int,
    page_no: int,
    num_of_rows: int,
) -> ParsedResponse:
    """특일 API 오퍼레이션의 특정 페이지를 호출하고 응답을 파싱한다."""

    response = await client.get(
        build_request_url(
            base_url=base_url,
            api_key=api_key,
            operation=operation,
            year=year,
            month=month,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )
    )
    response.raise_for_status()
    return parse_special_day_response(response.json())


def build_request_url(
    *,
    base_url: str,
    api_key: str,
    operation: str,
    year: int,
    month: int,
    page_no: int,
    num_of_rows: int,
) -> str:
    """ServiceKey 이중 인코딩을 피하기 위해 키를 마지막에 그대로 붙여 요청 URL을 만든다."""

    query = urlencode(
        {
            "solYear": f"{year:04d}",
            "solMonth": f"{month:02d}",
            "_type": "json",
            "pageNo": str(page_no),
            "numOfRows": str(num_of_rows),
        }
    )
    return f"{base_url}/{operation}?{query}&ServiceKey={api_key}"


async def collect_operation_month(
    repository: AnniversaryRepository,
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    operation: AnniversaryOperation,
    year: int,
    month: int,
    num_of_rows: int,
) -> CollectResult:
    """오퍼레이션과 월 하나를 호출해 저장한다."""

    parsed = await fetch_operation_month(
        client,
        base_url=base_url,
        api_key=api_key,
        operation=operation.name,
        year=year,
        month=month,
        num_of_rows=num_of_rows,
    )
    if parsed.result_code != "00":
        raise RuntimeError(
            f"{operation.name} 응답 실패: {parsed.result_code} {parsed.result_msg}"
        )

    saved_items = await repository.save_days(parsed.items)
    return CollectResult(
        saved_items=saved_items,
        skipped_items=parsed.skipped_items,
        total_count=parsed.total_count,
    )


def select_operations(
    operations: tuple[AnniversaryOperation, ...],
    selected_names: list[str] | None,
) -> tuple[AnniversaryOperation, ...]:
    """명령행에서 지정한 오퍼레이션만 선택한다."""

    if not selected_names:
        return operations

    by_name = {operation.name: operation for operation in operations}
    unknown = sorted(set(selected_names) - set(by_name))
    if unknown:
        raise ValueError(f"지원하지 않는 오퍼레이션입니다: {', '.join(unknown)}")
    return tuple(by_name[name] for name in selected_names)


async def async_main() -> int:
    """특일 API를 순회하며 실패한 호출은 로그로 남기고 다음 작업을 계속한다."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = parse_args()
    settings = load_settings()

    months = tuple(args.month or range(1, 13))
    operations = select_operations(settings.operations, args.operation)

    saved_total = 0
    skipped_total = 0
    failed_calls = 0

    connection = await connect(settings.database)
    try:
        repository = AnniversaryRepository(connection)
        if args.apply_schema:
            await repository.apply_schema(BASE_DIR / "table.sql")

        headers = {"User-Agent": settings.user_agent}
        async with httpx.AsyncClient(
            timeout=settings.http_timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            for month in months:
                for operation in operations:
                    try:
                        result = await collect_operation_month(
                            repository,
                            client,
                            base_url=settings.base_url,
                            api_key=settings.api_key,
                            operation=operation,
                            year=args.year if args.year is not None else date.today().year,
                            month=month,
                            num_of_rows=settings.num_of_rows,
                        )
                    except Exception:
                        failed_calls += 1
                        LOGGER.exception(
                            "특일 수집 실패: operation=%s, year=%s, month=%02d",
                            operation.name,
                            args.year,
                            month,
                        )
                        continue

                    saved_total += result.saved_items
                    skipped_total += result.skipped_items
                    LOGGER.info(
                        "특일 수집 완료: operation=%s, year=%s, month=%02d, "
                        "saved_items=%s, skipped_items=%s, total_count=%s",
                        operation.name,
                        args.year,
                        month,
                        result.saved_items,
                        result.skipped_items,
                        result.total_count,
                    )

        LOGGER.info(
            "특일 전체 수집 종료: saved_items=%s, skipped_items=%s, failed_calls=%s",
            saved_total,
            skipped_total,
            failed_calls,
        )
        return 1 if failed_calls else 0
    finally:
        await connection.close()


def main() -> int:
    """비동기 수집기 실행을 위한 동기 진입점이다."""

    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
