from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from models import ForecastValue


KST = ZoneInfo("Asia/Seoul")
SUCCESS_CODES = {"0", "00"}
VALID_CATEGORIES = {
    "POP",
    "PTY",
    "PCP",
    "REH",
    "SNO",
    "SKY",
    "TMP",
    "TMN",
    "TMX",
    "UUU",
    "VVV",
    "WAV",
    "VEC",
    "WSD",
}


@dataclass(frozen=True)
class ParsedForecastPage:
    """단기예보 API 한 페이지의 검증 결과다."""

    result_code: str
    result_msg: str
    values: tuple[ForecastValue, ...]
    total_count: int
    page_no: int
    num_of_rows: int
    raw_item_count: int
    skipped_items: int


def parse_forecast_page(payload: dict[str, Any]) -> ParsedForecastPage:
    """단기예보 JSON 응답 한 페이지를 내부 값으로 정규화한다."""

    response = _expect_mapping(payload.get("response"), "response")
    header = _expect_mapping(response.get("header"), "response.header")
    result_code = _clean_text(header.get("resultCode"))
    result_msg = _clean_text(header.get("resultMsg"))
    if not result_code:
        raise ValueError("API 응답에 resultCode가 없습니다.")

    body = _as_mapping(response.get("body"))
    if result_code not in SUCCESS_CODES:
        return ParsedForecastPage(
            result_code=result_code,
            result_msg=result_msg,
            values=(),
            total_count=_parse_non_negative_int(body.get("totalCount")) or 0,
            page_no=_parse_positive_int(body.get("pageNo")) or 1,
            num_of_rows=_parse_positive_int(body.get("numOfRows")) or 1,
            raw_item_count=0,
            skipped_items=0,
        )

    total_count = _required_non_negative_int(body.get("totalCount"), "totalCount")
    page_no = _required_positive_int(body.get("pageNo"), "pageNo")
    num_of_rows = _required_positive_int(body.get("numOfRows"), "numOfRows")
    raw_items = _extract_items(body.get("items"))

    values: list[ForecastValue] = []
    skipped_items = 0
    for raw_item in raw_items:
        value = parse_forecast_item(raw_item)
        if value is None:
            skipped_items += 1
            continue
        values.append(value)

    return ParsedForecastPage(
        result_code=result_code,
        result_msg=result_msg,
        values=tuple(values),
        total_count=total_count,
        page_no=page_no,
        num_of_rows=num_of_rows,
        raw_item_count=len(raw_items),
        skipped_items=skipped_items,
    )


def parse_forecast_item(raw_item: dict[str, Any]) -> ForecastValue | None:
    """단기예보 item 하나의 필드와 category별 값을 검증한다."""

    category = _clean_text(raw_item.get("category")).upper()
    value = _clean_text(raw_item.get("fcstValue"))
    if category not in VALID_CATEGORIES or not value or _is_missing(value):
        return None

    issued_at = _parse_kst_datetime(
        raw_item.get("baseDate"), raw_item.get("baseTime")
    )
    forecast_at = _parse_kst_datetime(
        raw_item.get("fcstDate"), raw_item.get("fcstTime")
    )
    nx = _parse_positive_int(raw_item.get("nx"))
    ny = _parse_positive_int(raw_item.get("ny"))
    if issued_at is None or forecast_at is None or nx is None or ny is None:
        return None
    if forecast_at <= issued_at or not 1 <= nx <= 149 or not 1 <= ny <= 253:
        return None
    if not _is_valid_category_value(category, value):
        return None

    return ForecastValue(
        issued_at=issued_at,
        forecast_at=forecast_at,
        nx=nx,
        ny=ny,
        category=category,
        value=value,
    )


def _is_valid_category_value(category: str, value: str) -> bool:
    if category == "SKY":
        return value in {"1", "3", "4"}
    if category == "PTY":
        return value in {"0", "1", "2", "3", "4"}
    if category in {"POP", "REH"}:
        number = _decimal(value)
        return (
            number is not None
            and number == number.to_integral()
            and 0 <= number <= 100
        )
    if category == "VEC":
        number = _decimal(value)
        return number is not None and 0 <= number <= 360
    if category in {"TMP", "TMN", "TMX"}:
        number = _decimal(value)
        return number is not None and -100 <= number <= 100
    if category in {"UUU", "VVV"}:
        number = _decimal(value)
        return number is not None and -200 <= number <= 200
    if category in {"WAV", "WSD"}:
        number = _decimal(value)
        return number is not None and 0 <= number <= 200
    return True


def _is_missing(value: str) -> bool:
    number = _decimal(value)
    return number is not None and (number >= 900 or number <= -900)


def _decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _parse_kst_datetime(raw_date: Any, raw_time: Any) -> datetime | None:
    date_text = _clean_text(raw_date)
    time_text = _clean_text(raw_time)
    if not date_text.isdigit() or not time_text.isdigit():
        return None
    if len(date_text) != 8 or len(time_text) > 4:
        return None
    time_text = time_text.zfill(4)
    try:
        return datetime.strptime(date_text + time_text, "%Y%m%d%H%M").replace(
            tzinfo=KST
        )
    except ValueError:
        return None


def _extract_items(raw_items: Any) -> list[dict[str, Any]]:
    items = _as_mapping(raw_items)
    if not items:
        return []
    raw_item = items.get("item")
    if raw_item is None or raw_item == "":
        return []
    if isinstance(raw_item, dict):
        return [raw_item]
    if isinstance(raw_item, list):
        return [item for item in raw_item if isinstance(item, dict)]
    return []


def _required_non_negative_int(value: Any, field: str) -> int:
    parsed = _parse_non_negative_int(value)
    if parsed is None:
        raise ValueError(f"API 응답의 {field} 값이 올바르지 않습니다.")
    return parsed


def _required_positive_int(value: Any, field: str) -> int:
    parsed = _parse_positive_int(value)
    if parsed is None:
        raise ValueError(f"API 응답의 {field} 값이 올바르지 않습니다.")
    return parsed


def _parse_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_positive_int(value: Any) -> int | None:
    parsed = _parse_non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _expect_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"API 응답의 {field} 형식이 올바르지 않습니다.")
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
