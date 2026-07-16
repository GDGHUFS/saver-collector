from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from urllib.parse import urlencode

import httpx

from config import CollectorSettings
from models import FetchedForecast, ForecastValue, GridPoint
from parser import ParsedForecastPage, SUCCESS_CODES, parse_forecast_page


TRANSIENT_RESULT_CODES = {"01", "02", "03", "04", "05", "21", "99"}


class WeatherApiError(RuntimeError):
    """API 호출 또는 응답 계약 위반을 키가 없는 메시지로 표현한다."""


class DailyRequestLimitError(WeatherApiError):
    """DB에 기록된 KST 일일 요청 예산이 소진되었음을 나타낸다."""


class FatalWeatherApiError(WeatherApiError):
    """인증·요청 설정처럼 이후 모든 격자 호출을 중단할 오류다."""


class RequestPacer:
    """공유 HTTP 클라이언트의 초당 요청 수를 제한한다."""

    def __init__(self, requests_per_second: float):
        self.interval = 1.0 / requests_per_second
        self.lock = asyncio.Lock()
        self.last_request_at = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self.lock:
            now = loop.time()
            remaining = self.interval - (now - self.last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self.last_request_at = loop.time()


class WeatherApiClient:
    """기상청 단기예보의 모든 페이지를 비동기로 호출한다."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: CollectorSettings,
        reserve_request: Callable[[], Awaitable[bool]] | None = None,
    ):
        if not settings.api_key:
            raise ValueError("단기예보 API 키가 필요합니다.")
        self.client = client
        self.settings = settings
        self.pacer = RequestPacer(settings.requests_per_second)
        self.reserve_request = reserve_request
        self.request_budget_exhausted = False
        self.fatal_error: FatalWeatherApiError | None = None

    async def fetch_forecast(
        self,
        grid: GridPoint,
        issued_at: datetime,
    ) -> FetchedForecast:
        """격자와 발표시각 하나의 전체 단기예보를 수집한다."""

        page_no = 1
        total_count: int | None = None
        skipped_items = 0
        raw_item_count = 0
        values: dict[tuple[datetime, str], ForecastValue] = {}

        while True:
            page = await self._fetch_page(grid, issued_at, page_no)
            if page.page_no != page_no:
                raise WeatherApiError(
                    f"응답 페이지 번호 불일치: expected={page_no}, actual={page.page_no}"
                )
            if total_count is None:
                total_count = page.total_count
            elif total_count != page.total_count:
                raise WeatherApiError("페이지별 totalCount가 서로 다릅니다.")

            _validate_page_values(page, grid, issued_at)
            for value in page.values:
                values[(value.forecast_at, value.category)] = value
            skipped_items += page.skipped_items
            raw_item_count += page.raw_item_count

            if page.page_no * page.num_of_rows >= page.total_count:
                break
            if page.raw_item_count == 0:
                raise WeatherApiError("마지막 페이지 전에 빈 item 목록을 받았습니다.")
            page_no += 1

        if total_count is None or total_count <= 0:
            raise WeatherApiError("단기예보 응답에 저장할 데이터가 없습니다.")
        if raw_item_count < total_count:
            raise WeatherApiError(
                f"전체 항목 수가 totalCount보다 작습니다: {raw_item_count}/{total_count}"
            )
        if not values:
            raise WeatherApiError("검증을 통과한 단기예보 항목이 없습니다.")

        return FetchedForecast(
            grid=grid,
            issued_at=issued_at,
            values=tuple(values[key] for key in sorted(values)),
            total_count=total_count,
            skipped_items=skipped_items,
            page_count=page_no,
        )

    async def _fetch_page(
        self,
        grid: GridPoint,
        issued_at: datetime,
        page_no: int,
    ) -> ParsedForecastPage:
        last_error: WeatherApiError | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            if self.fatal_error is not None:
                raise self.fatal_error
            if self.request_budget_exhausted:
                raise DailyRequestLimitError("KST 일일 API 요청 예산을 소진했습니다.")
            if self.reserve_request is not None and not await self.reserve_request():
                self.request_budget_exhausted = True
                raise DailyRequestLimitError("KST 일일 API 요청 예산을 소진했습니다.")
            try:
                await self.pacer.wait()
                response = await self.client.get(
                    build_request_url(
                        base_url=self.settings.base_url,
                        api_key=self.settings.api_key or "",
                        issued_at=issued_at,
                        grid=grid,
                        page_no=page_no,
                        num_of_rows=self.settings.num_of_rows,
                    )
                )
                response.raise_for_status()
                page = parse_forecast_page(response.json())
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                last_error = WeatherApiError(f"HTTP 응답 실패: status={status_code}")
                retryable = status_code in {408, 425, 429} or status_code >= 500
                if not retryable:
                    self.fatal_error = FatalWeatherApiError(str(last_error))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = WeatherApiError(f"HTTP 전송 실패: {type(exc).__name__}")
                retryable = True
            except (ValueError, TypeError) as exc:
                last_error = WeatherApiError(f"API 응답 파싱 실패: {exc}")
                retryable = True
            else:
                if page.result_code in SUCCESS_CODES:
                    return page
                last_error = WeatherApiError(
                    f"API 응답 실패: code={page.result_code}, msg={page.result_msg}"
                )
                retryable = page.result_code in TRANSIENT_RESULT_CODES
                if not retryable:
                    self.fatal_error = FatalWeatherApiError(str(last_error))

            if not retryable or attempt >= self.settings.max_attempts:
                break
            await asyncio.sleep(self.settings.retry_base_delay * (2 ** (attempt - 1)))

        if last_error is None:
            last_error = WeatherApiError("알 수 없는 단기예보 API 오류입니다.")
        if self.fatal_error is not None:
            raise self.fatal_error from None
        raise last_error from None


def build_request_url(
    *,
    base_url: str,
    api_key: str,
    issued_at: datetime,
    grid: GridPoint,
    page_no: int,
    num_of_rows: int,
) -> str:
    """이미 인코딩된 서비스키의 이중 인코딩을 피한 요청 URL을 만든다."""

    query = urlencode(
        {
            "pageNo": str(page_no),
            "numOfRows": str(num_of_rows),
            "dataType": "JSON",
            "base_date": issued_at.strftime("%Y%m%d"),
            "base_time": issued_at.strftime("%H%M"),
            "nx": str(grid.nx),
            "ny": str(grid.ny),
        }
    )
    return f"{base_url.rstrip('/')}/getVilageFcst?{query}&serviceKey={api_key}"


def _validate_page_values(
    page: ParsedForecastPage,
    grid: GridPoint,
    issued_at: datetime,
) -> None:
    for value in page.values:
        if value.nx != grid.nx or value.ny != grid.ny:
            raise WeatherApiError(
                f"응답 격자 불일치: expected=({grid.nx},{grid.ny}), "
                f"actual=({value.nx},{value.ny})"
            )
        if value.issued_at != issued_at:
            raise WeatherApiError(
                "응답 발표시각이 요청 발표시각과 일치하지 않습니다."
            )
